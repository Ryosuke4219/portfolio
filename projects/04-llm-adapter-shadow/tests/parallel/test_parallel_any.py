from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import Future
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from src.llm_adapter.errors import RateLimitError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError, run_parallel_any_sync
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import Runner
from src.llm_adapter.runner_config import BackoffPolicy, RunnerConfig, RunnerMode

from ..parallel_helpers import (
    _install_recording_executor,
    _read_metrics,
    _RetryProbeProvider,
    _StaticProvider,
    RecordingLogger,
)

# --- ANY のキャンセル/再試行 ---

def test_run_parallel_any_sync_cancels_pending_futures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_recording_executor(monkeypatch)
    assert created == []

    cancelled_futures: set[Future[Any]] = set()
    original_cancel = Future.cancel

    def _tracking_cancel(self: Future[Any]) -> bool:
        cancelled_futures.add(self)
        return original_cancel(self)

    monkeypatch.setattr(Future, "cancel", _tracking_cancel, raising=False)

    slow_gate = threading.Event()

    def _slow_worker(name: str) -> str:
        slow_gate.wait(timeout=0.25)
        return name

    def _fast_worker() -> str:
        return "fast"

    cancelled_indices: list[Sequence[int]] = []

    result = run_parallel_any_sync(
        (
            lambda: _slow_worker("slow-1"),
            _fast_worker,
            lambda: _slow_worker("slow-2"),
        ),
        on_cancelled=lambda indices: cancelled_indices.append(tuple(indices)),
    )

    assert result == "fast"
    assert cancelled_indices == [tuple(sorted((0, 2)))]
    assert len(created) == 1
    executor = created[0]
    assert len(executor.submitted) == 3
    assert executor.submitted[0] in cancelled_futures
    assert executor.submitted[1] not in cancelled_futures
    assert executor.submitted[2] in cancelled_futures

    slow_gate.set()


def test_runner_parallel_any_records_failures() -> None:
    provider_a = _RetryProbeProvider(
        "fail-a",
        [TimeoutError("primary timeout")],
    )
    provider_b = _RetryProbeProvider(
        "fail-b",
        [RateLimitError("secondary limit")],
    )
    runner = Runner(
        [provider_a, provider_b],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY),
    )
    request = ProviderRequest(prompt="fail", model="parallel-any-fail")

    with pytest.raises(ParallelExecutionError) as excinfo:
        runner.run(request, shadow=None)

    failures = excinfo.value.failures
    assert failures is not None
    assert failures == [
        {
            "provider": "fail-a",
            "attempt": "1",
            "summary": "TimeoutError: primary timeout",
        },
        {
            "provider": "fail-b",
            "attempt": "2",
            "summary": "RateLimitError: secondary limit",
        },
    ]


def test_parallel_any_primitives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)
    failing = MockProvider("fail", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    fast = MockProvider("fast", base_latency_ms=1, error_markers=set())
    fail_request = ProviderRequest(prompt="[TIMEOUT] hi", model="m1")
    ok_request = ProviderRequest(prompt="hi", model="m2")
    winner = run_parallel_any_sync(
        (
            lambda: failing.invoke(fail_request),
            lambda: fast.invoke(ok_request),
        )
    )
    assert winner.text.startswith("echo(fast):")


def test_runner_parallel_any_returns_success_after_fast_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingProvider:
        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            raise TimeoutError("fast failure")

    class _SlowProvider(_StaticProvider):
        def __init__(self, name: str, text: str, latency_ms: int, delay: float) -> None:
            super().__init__(name, text, latency_ms)
            self._delay = delay

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            time.sleep(self._delay)
            return super().invoke(request)

    providers: list[ProviderSPI] = [
        _FailingProvider("fail-fast"),
        _SlowProvider("slow-success", "slow-ok", latency_ms=5, delay=0.05),
    ]
    cost_calls: list[tuple[object, int, int]] = []

    def _record_cost(provider: object, tokens_in: int, tokens_out: int) -> float:
        cost_calls.append((provider, tokens_in, tokens_out))
        return 0.0

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync.estimate_cost", _record_cost, raising=False
    )
    logger = RecordingLogger()
    runner = Runner(
        providers,
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=1),
    )
    request = ProviderRequest(prompt="hello", model="m-parallel-any")

    response = runner.run(request)

    assert response.text == "slow-ok"
    run_metric_events = [
        event for event in logger.of_type("run_metric") if event["status"] == "ok"
    ]
    assert len(run_metric_events) == 1
    assert run_metric_events[0]["attempts"] == 2
    assert len(cost_calls) == 1
    cost_provider, cost_tokens_in, cost_tokens_out = cost_calls[0]
    assert cost_provider is providers[1]
    assert (cost_tokens_in, cost_tokens_out) == (1, 1)


def test_runner_parallel_any_logs_cancelled_providers() -> None:
    class _SlowProvider(_StaticProvider):
        def __init__(self, name: str, text: str, latency_ms: int, delay: float) -> None:
            super().__init__(name, text, latency_ms)
            self._delay = delay

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            time.sleep(self._delay)
            return super().invoke(request)

    fast = _StaticProvider("fast", "fast-ok", latency_ms=1)
    slow = _SlowProvider("slow", "slow-ok", latency_ms=10, delay=0.1)
    logger = RecordingLogger()
    runner = Runner(
        [fast, slow],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hello", model="parallel-any-cancel")

    response = runner.run(request)

    assert response.text == "fast-ok"
    provider_calls = {
        event["provider"]: event for event in logger.of_type("provider_call")
    }
    assert provider_calls["fast"]["status"] == "ok"
    assert provider_calls["slow"]["status"] == "error"
    assert provider_calls["slow"]["outcome"] == "error"
    assert provider_calls["slow"].get("error_type") == "CancelledError"
    run_metrics = {
        event["provider"]: event
        for event in logger.of_type("run_metric")
        if event["provider"] is not None
    }
    assert run_metrics["fast"]["status"] == "ok"
    assert run_metrics["slow"]["status"] == "error"
    assert run_metrics["slow"]["outcome"] == "error"
    assert run_metrics["slow"].get("error_type") == "CancelledError"


def test_runner_parallel_any_retries_until_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda delay: sleep_calls.append(delay))
    executors = _install_recording_executor(monkeypatch)
    provider = _RetryProbeProvider(
        "retry-any",
        [RateLimitError("retry"), "final"],
        latency_s=0.001,
    )
    runner = Runner(
        [provider, provider, provider],
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            max_concurrency=1,
            max_attempts=2,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.05),
        ),
    )
    request = ProviderRequest(prompt="retry", model="parallel-any-retry")
    metrics_path = tmp_path / "parallel_any_retry.jsonl"

    response = runner.run(request, shadow=None, shadow_metrics_path=metrics_path)

    assert response.text.endswith("final")
    assert provider.call_count == 2
    assert len(sleep_calls) == provider.call_count
    executor = executors[-1]
    assert len(executor.submitted) == provider.call_count
    assert all(f.done() or f.cancelled() for f in executor.submitted)

    events = _read_metrics(metrics_path)
    provider_calls = sorted(
        (event for event in events if event["event"] == "provider_call"),
        key=lambda event: event["attempt"],
    )
    assert [event["attempt"] for event in provider_calls] == [1, 2]
    assert provider_calls[0]["status"] == "error"
    assert provider_calls[0]["error_type"] == "RateLimitError"
    assert provider_calls[1]["status"] == "ok"
    run_metrics = [
        event
        for event in events
        if event["event"] == "run_metric" and event["status"] == "ok"
    ]
    assert len(run_metrics) == 1
    assert run_metrics[0]["attempts"] == 2

