from __future__ import annotations

import asyncio

from src.llm_adapter.errors import TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner import AsyncRunner, ParallelAllResult
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode

from .conftest import (
    _AsyncProbeProvider,
    _CapturingLogger,
)
from .parallel import *  # noqa: F401,F403


def test_async_parallel_any_run_metric_uses_response_latency() -> None:
    class _FixedLatencyProvider:
        def __init__(self, name: str, latency_ms: int) -> None:
            self._name = name
            self._latency_ms = latency_ms

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                text=f"{self._name}:{request.prompt}",
                latency_ms=self._latency_ms,
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
            )

    latency_ms = 4321
    provider = _FixedLatencyProvider("fixed", latency_ms=latency_ms)
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [provider],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=1),
    )
    request = ProviderRequest(prompt="hi", model="latency-check")

    response = asyncio.run(runner.run_async(request))

    assert response.latency_ms == latency_ms
    run_metrics = [
        event
        for event in logger.of_type("run_metric")
        if event.get("provider") == provider.name()
    ]
    assert len(run_metrics) == 1
    assert run_metrics[0]["latency_ms"] == latency_ms


def test_async_runner_parallel_any_logs_cancelled_providers() -> None:
    fast = _AsyncProbeProvider("fast", delay=0.0, text="fast")
    slow = _AsyncProbeProvider("slow", delay=0.2, text="slow")
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [fast, slow],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="async-parallel-any-cancel")

    response = asyncio.run(runner.run_async(request))

    assert response.text == "fast:hi"
    provider_calls = {
        event["provider"]: event for event in logger.of_type("provider_call")
    }
    assert provider_calls["fast"]["status"] == "ok"
    assert provider_calls["slow"]["status"] == "error"
    assert provider_calls["slow"]["error_type"] == "CancelledError"
    run_metrics = {
        event["provider"]: event for event in logger.of_type("run_metric")
        if event["provider"] is not None
    }
    assert run_metrics["fast"]["status"] == "ok"
    assert run_metrics["slow"]["status"] == "error"
    assert run_metrics["slow"]["error_type"] == "CancelledError"


def test_async_runner_parallel_any_logs_timeout_failures_in_run_metrics() -> None:
    class _TimeoutProvider:
        def __init__(self, name: str, delay: float) -> None:
            self._name = name
            self._delay = delay

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
            await asyncio.sleep(self._delay)
            raise TimeoutError("operation timed out")

    timeout_provider = _TimeoutProvider("timeout", delay=0.01)
    success_provider = _AsyncProbeProvider("success", delay=0.05, text="success")
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [timeout_provider, success_provider],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="async-parallel-any-timeout")

    response = asyncio.run(runner.run_async(request))

    assert response.text == "success:hi"

    run_metrics = [
        event
        for event in logger.of_type("run_metric")
        if event.get("provider") in {timeout_provider.name(), success_provider.name()}
    ]
    assert len(run_metrics) == 2
    timeout_events = [
        event for event in run_metrics if event.get("provider") == timeout_provider.name()
    ]
    assert len(timeout_events) == 1
    timeout_metric = timeout_events[0]
    assert timeout_metric["status"] == "error"
    assert timeout_metric["outcome"] == "error"
    assert timeout_metric["error_type"] == "TimeoutError"

    success_events = [
        event for event in run_metrics if event.get("provider") == success_provider.name()
    ]
    assert len(success_events) == 1
    assert success_events[0]["status"] == "ok"


def test_async_parallel_all_emits_run_metric_per_provider() -> None:
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    slow = _AsyncProbeProvider("slow", delay=0.02, text="slow")
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [fast, slow],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="async-parallel-all-run-metric")

    result = asyncio.run(runner.run_async(request))

    assert isinstance(result, ParallelAllResult)
    run_metrics = [
        event
        for event in logger.of_type("run_metric")
        if event.get("provider") in {fast.name(), slow.name()}
    ]
    assert len(run_metrics) == 2
    providers_logged = {event["provider"] for event in run_metrics}
    assert providers_logged == {fast.name(), slow.name()}
    expected_latency = {
        provider.name(): response.latency_ms for _, provider, response, _ in result
    }
    expected_attempts = {
        provider.name(): attempt_index for attempt_index, provider, *_ in result
    }
    for event in run_metrics:
        provider_name = event["provider"]
        assert event["latency_ms"] == expected_latency[provider_name]
        assert event["attempts"] == expected_attempts[provider_name]
def test_async_parallel_any_returns_first_completion() -> None:
    slow = _AsyncProbeProvider("slow", delay=0.1, text="slow")
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    runner = AsyncRunner(
        [slow, fast],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="model-parallel-any")

    async def _execute() -> ProviderResponse:
        result = await runner.run_async(request)
        assert isinstance(result, ProviderResponse)
        return result

    _ = asyncio.run(asyncio.wait_for(_execute(), timeout=0.2))

# チェックリスト:
# - [ ] 新規テストは ``projects/04-llm-adapter/tests/runner_async`` へ追加する
# - [ ] 互換性が不要になったらこのシムを削除する
