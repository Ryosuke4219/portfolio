from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import CancelledError
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.llm_adapter.errors import ProviderSkip
from src.llm_adapter.observability import EventLogger
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner_shared import RateLimiter
from src.llm_adapter.runner_sync_invocation import (
    CancelledResultsBuilder,
    ParallelResultLogger,
    ProviderInvocationResult,
    ProviderInvoker,
)
from src.llm_adapter.shadow import ShadowMetrics


class _RecorderLogger(EventLogger):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: dict[str, Any]) -> None:  # type: ignore[override]
        self.events.append((event_type, dict(record)))


class _StubProvider:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:  # pragma: no cover - protocol compat
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - unused
        raise NotImplementedError


class _FakeMetrics(ShadowMetrics):
    def __init__(self) -> None:
        super().__init__(payload={}, logger=None)
        self.emitted: list[Mapping[str, Any] | None] = []

    def emit(self, extra: Mapping[str, Any] | None = None) -> None:
        self.emitted.append(extra)


def _make_response() -> ProviderResponse:
    return ProviderResponse(
        "ok",
        latency_ms=42,
        token_usage=TokenUsage(prompt=3, completion=5),
    )


def test_invoker_returns_shadow_metrics_after_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _StubProvider("primary")
    shadow = _StubProvider("shadow")
    request = ProviderRequest(model="gpt", prompt="hi")
    response = _make_response()
    metrics = _FakeMetrics()
    rate_calls: list[str] = []
    rate_limiter_ns = SimpleNamespace(acquire=lambda: None)
    monkeypatch.setattr(rate_limiter_ns, "acquire", lambda: rate_calls.append("acquire"))
    rate_limiter = cast(RateLimiter, rate_limiter_ns)

    run_calls: list[tuple[Any, ...]] = []

    def fake_run_with_shadow(*args: Any, **kwargs: Any) -> tuple[ProviderResponse, _FakeMetrics]:
        run_calls.append(args)
        assert rate_calls == ["acquire"]
        assert kwargs["capture_metrics"] is True
        return response, metrics

    log_provider_call_args: list[dict[str, Any]] = []

    def fake_log_provider_call(*_: Any, **kwargs: Any) -> None:
        log_provider_call_args.append(dict(kwargs))

    invoker = ProviderInvoker(
        rate_limiter=rate_limiter,
        run_with_shadow=cast(Any, fake_run_with_shadow),
        log_provider_call=fake_log_provider_call,
        log_provider_skipped=lambda *a, **k: None,
        time_fn=lambda: 10.0,
        elapsed_ms=lambda start: 7,
    )

    result = invoker.invoke(
        provider,
        request,
        attempt=1,
        total_providers=2,
        event_logger=_RecorderLogger(),
        request_fingerprint="fp",
        metadata={},
        shadow=shadow,
        metrics_path="path.jsonl",
        capture_shadow_metrics=True,
    )

    assert rate_calls == ["acquire"]
    assert run_calls and run_calls[0][0] is provider
    assert result.response is response
    assert result.shadow_metrics is metrics
    assert result.error is None
    assert log_provider_call_args and log_provider_call_args[-1]["status"] == "ok"


def test_provider_call_event_includes_token_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _StubProvider("primary")
    request = ProviderRequest(model="gpt", prompt="hi")
    response = _make_response()
    logger = _RecorderLogger()

    def fake_run_with_shadow(*args: Any, **kwargs: Any) -> ProviderResponse:
        assert args[0] is provider
        assert kwargs["capture_metrics"] is False
        return response

    invoker = ProviderInvoker(
        rate_limiter=None,
        run_with_shadow=cast(Any, fake_run_with_shadow),
        time_fn=lambda: 1.0,
        elapsed_ms=lambda start: 5,
    )

    result = invoker.invoke(
        provider,
        request,
        attempt=1,
        total_providers=1,
        event_logger=logger,
        request_fingerprint="fp",
        metadata={},
        shadow=None,
        metrics_path=None,
        capture_shadow_metrics=False,
    )

    assert result.error is None
    provider_calls = [event for event in logger.events if event[0] == "provider_call"]
    assert len(provider_calls) == 1
    payload = provider_calls[0][1]
    token_usage = payload.get("token_usage")
    assert token_usage == {"prompt": 3, "completion": 5, "total": 8}
    assert all(isinstance(value, int) for value in token_usage.values())


def test_invoker_logs_skip_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _StubProvider("primary")
    request = ProviderRequest(model="gpt", prompt="hi")
    skip_error = ProviderSkip("skip")

    log_skipped: list[dict[str, Any]] = []
    log_calls: list[dict[str, Any]] = []

    def fake_log_skipped(*_: Any, **kwargs: Any) -> None:
        log_skipped.append(dict(kwargs))

    def fake_log_call(*_: Any, **kwargs: Any) -> None:
        log_calls.append(dict(kwargs))

    invoker = ProviderInvoker(
        rate_limiter=None,
        run_with_shadow=cast(Any, lambda *a, **k: (_ for _ in ()).throw(skip_error)),
        log_provider_call=fake_log_call,
        log_provider_skipped=fake_log_skipped,
        time_fn=time.time,
        elapsed_ms=lambda start: 11,
    )

    result = invoker.invoke(
        provider,
        request,
        attempt=1,
        total_providers=1,
        event_logger=_RecorderLogger(),
        request_fingerprint="fp",
        metadata={},
        shadow=None,
        metrics_path=None,
        capture_shadow_metrics=False,
    )

    assert result.error is skip_error
    assert len(log_skipped) == 1
    assert log_skipped[0]["error"] is skip_error
    assert len(log_calls) == 1
    assert log_calls[0]["status"] == "error"

    non_skip_error = RuntimeError("boom")
    invoker_non_skip = ProviderInvoker(
        rate_limiter=None,
        run_with_shadow=cast(Any, lambda *a, **k: (_ for _ in ()).throw(non_skip_error)),
        log_provider_call=fake_log_call,
        log_provider_skipped=fake_log_skipped,
        time_fn=time.time,
        elapsed_ms=lambda start: 17,
    )

    log_skipped.clear()
    log_calls.clear()

    result_non_skip = invoker_non_skip.invoke(
        provider,
        request,
        attempt=1,
        total_providers=1,
        event_logger=_RecorderLogger(),
        request_fingerprint="fp",
        metadata={},
        shadow=None,
        metrics_path=None,
        capture_shadow_metrics=False,
    )

    assert result_non_skip.error is non_skip_error
    assert log_skipped == []
    assert len(log_calls) == 1
    assert log_calls[0]["error"] is non_skip_error


def test_cancelled_results_skip_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [_StubProvider("primary"), _StubProvider("secondary")]
    results: list[ProviderInvocationResult | None] = [None, None]
    builder = CancelledResultsBuilder(run_started=1.0, elapsed_ms=lambda start: 99)

    builder.apply(results, providers=providers, cancelled_indices=[0, 1], total_providers=2)

    assert all(isinstance(entry, ProviderInvocationResult) for entry in results)
    assert all(isinstance(entry.error, CancelledError) for entry in results if entry is not None)


    logger = _RecorderLogger()
    log_run_metric_calls: list[dict[str, Any]] = []

    def fake_log_run_metric(*_: Any, **kwargs: Any) -> None:
        log_run_metric_calls.append(dict(kwargs))

    parallel_logger = ParallelResultLogger(
        log_provider_call=lambda *a, **k: None,
        log_run_metric=fake_log_run_metric,
        estimate_cost=lambda provider, tokens_in, tokens_out: 0.0,
        elapsed_ms=lambda start: 13,
    )

    parallel_logger.log_results(
        results,
        event_logger=logger,
        request=ProviderRequest(model="gpt", prompt="hi"),
        request_fingerprint="fp",
        metadata={},
        run_started=0.0,
        shadow_used=False,
        skip=tuple(result for result in results if result is not None),
    )

    assert log_run_metric_calls == []
    assert all(isinstance(entry.error, CancelledError) for entry in results if entry is not None)


def test_provider_call_event_contains_token_usage() -> None:
    provider = _StubProvider("primary")
    request = ProviderRequest(model="gpt", prompt="hi")
    response = _make_response()
    event_logger = _RecorderLogger()

    def fake_run_with_shadow(*args: Any, **kwargs: Any) -> ProviderResponse:
        assert kwargs["capture_metrics"] is False
        return response

    invoker = ProviderInvoker(
        rate_limiter=None,
        run_with_shadow=cast(Any, fake_run_with_shadow),
        time_fn=lambda: 0.0,
        elapsed_ms=lambda start: 1,
    )

    invoker.invoke(
        provider,
        request,
        attempt=1,
        total_providers=1,
        event_logger=event_logger,
        request_fingerprint="fp",
        metadata={},
        shadow=None,
        metrics_path=None,
        capture_shadow_metrics=False,
    )

    provider_call_events = [record for event, record in event_logger.events if event == "provider_call"]
    assert provider_call_events, "provider_call event not emitted"
    latest = provider_call_events[-1]
    token_usage = latest.get("token_usage")
    assert isinstance(token_usage, dict)
    assert token_usage == {"prompt": 3, "completion": 5, "total": 8}
    for key in ("prompt", "completion", "total"):
        assert isinstance(token_usage[key], int)
