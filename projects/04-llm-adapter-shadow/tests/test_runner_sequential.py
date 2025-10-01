from __future__ import annotations

import time
from typing import Any

import pytest

from src.llm_adapter.errors import AllFailedError, AuthError, TimeoutError
from src.llm_adapter.observability import EventLogger
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner_config import RunnerConfig
from src.llm_adapter.runner_sync import ProviderInvocationResult, Runner
from src.llm_adapter.runner_sync_modes import SequentialStrategy, SyncRunContext


class _FailingProvider:
    def __init__(self, name: str, error: Exception) -> None:
        self._name = name
        self._error = error
        self.calls = 0

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        raise self._error


def test_sequential_raises_all_failed_error_with_cause() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hello")
    first_error = TimeoutError("slow")
    second_error = TimeoutError("boom")
    providers = [
        _FailingProvider("first", first_error),
        _FailingProvider("second", second_error),
    ]
    runner = Runner(providers, config=RunnerConfig())

    with pytest.raises(AllFailedError) as exc_info:
        runner.run(request)

    error = exc_info.value
    assert error.__cause__ is second_error
    assert providers[0].calls == 1
    assert providers[1].calls == 1


class _RecordingLogger(EventLogger):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: dict[str, Any]) -> None:  # type: ignore[override]
        self.events.append((event_type, dict(record)))


def _make_context(runner: Runner, *, logger: EventLogger | None = None) -> SyncRunContext:
    return SyncRunContext(
        runner=runner,
        request=ProviderRequest(model="gpt-test", prompt="hello"),
        event_logger=logger,
        metadata={},
        run_started=time.time(),
        request_fingerprint="fp",  # 任意の固定値
        shadow=None,
        shadow_used=False,
        metrics_path=None,
        run_parallel_all=lambda workers, **_: [],
        run_parallel_any=lambda workers, **_: workers[0](),
    )


def test_sequential_strategy_emits_fallback_for_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [_FailingProvider("primary", TimeoutError("boom")), _FailingProvider("secondary", TimeoutError("boom"))]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    response = ProviderResponse("ok", latency_ms=10, token_usage=TokenUsage(prompt=0, completion=0))

    def fake_invoke(
        provider: Any,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        **_: Any,
    ) -> ProviderInvocationResult:
        if provider.name() == "primary":
            return ProviderInvocationResult(
                provider=provider,
                attempt=attempt,
                total_providers=total_providers,
                response=None,
                error=AuthError("bad key"),
                latency_ms=5,
                tokens_in=None,
                tokens_out=None,
                shadow_metrics=None,
                shadow_metrics_extra=None,
                provider_call_logged=True,
            )
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=response,
            error=None,
            latency_ms=5,
            tokens_in=0,
            tokens_out=0,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)

    result = strategy.execute(context)

    assert result is response
    fallback_events = [event for event in logger.events if event[0] == "provider_fallback"]
    assert len(fallback_events) == 1
    event_type, payload = fallback_events[0]
    assert event_type == "provider_fallback"
    assert payload["provider"] == "primary"
    assert payload["attempt"] == 1


def test_sequential_strategy_all_failed_logs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [_FailingProvider("primary", TimeoutError("slow")), _FailingProvider("secondary", TimeoutError("boom"))]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    errors = {
        "primary": TimeoutError("slow"),
        "secondary": TimeoutError("boom"),
    }

    def fake_invoke(
        provider: Any,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        **_: Any,
    ) -> ProviderInvocationResult:
        error = errors[provider.name()]
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=None,
            error=error,
            latency_ms=5,
            tokens_in=None,
            tokens_out=None,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)

    log_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_log_run_metric(*args: Any, **kwargs: Any) -> None:
        log_calls.append((args, kwargs))

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync_modes.log_run_metric",
        fake_log_run_metric,
    )

    with pytest.raises(AllFailedError) as exc_info:
        strategy.execute(context)

    message = str(exc_info.value)
    assert "primary (attempt 1)" in message
    assert "secondary (attempt 2)" in message
    assert len(log_calls) == 1
    assert log_calls[0][1]["status"] == "error"
