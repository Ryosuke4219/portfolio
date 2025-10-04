from __future__ import annotations

import asyncio

from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner import AsyncRunner
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode

from .conftest import _AsyncProbeProvider, _CapturingLogger


def test_async_parallel_any_run_metric_uses_response_latency() -> None:
    class _FixedLatencyAsyncProvider:
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

    fixed_latency = 321
    provider = _FixedLatencyAsyncProvider("fixed", latency_ms=fixed_latency)
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [provider],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=1),
    )
    request = ProviderRequest(prompt="latency", model="parallel-any-latency")

    response = asyncio.run(runner.run_async(request))

    assert response.latency_ms == fixed_latency
    run_metrics = logger.of_type("run_metric")
    assert len(run_metrics) == 1
    assert run_metrics[0]["latency_ms"] == fixed_latency


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

    response = asyncio.run(asyncio.wait_for(_execute(), timeout=0.2))

    assert response.text.startswith("fast:")


def test_async_parallel_any_cancellation_waits_for_cleanup() -> None:
    slow = _AsyncProbeProvider("slow", delay=0.2, text="slow")
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    runner = AsyncRunner(
        [slow, fast],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="model-parallel-cancel")

    async def _execute() -> ProviderResponse:
        result = await runner.run_async(request)
        assert isinstance(result, ProviderResponse)
        return result

    response = asyncio.run(asyncio.wait_for(_execute(), timeout=0.3))

    assert response.text.startswith("fast:")
    assert slow.cancelled is True
    assert slow.finished is True
