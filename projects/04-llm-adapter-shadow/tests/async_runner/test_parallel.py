from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.llm_adapter.errors import RateLimitError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner import AsyncRunner, ParallelAllResult
from src.llm_adapter.runner_async import AllFailedError
from src.llm_adapter.runner_config import BackoffPolicy, RunnerConfig, RunnerMode

from .conftest import (
    _AsyncProbeProvider,
    _CapturingLogger,
    _FakeClock,
    _patch_runner_sleep,
)


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


def test_async_parallel_any_rate_limit_does_not_retry() -> None:
    providers = [
        _AsyncProbeProvider("rl_a", delay=0.0, failures=[RateLimitError("a")]),
        _AsyncProbeProvider("rl_b", delay=0.0),
    ]
    logger = _CapturingLogger()
    runner = AsyncRunner(
        providers,
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="rl", model="model-parallel-any-rl")

    async def _execute() -> ProviderResponse:
        result = await runner.run_async(request)
        assert isinstance(result, ProviderResponse)
        return result

    response = asyncio.run(asyncio.wait_for(_execute(), timeout=0.2))

    assert response.text == "rl_b:rl"
    assert [provider.invocations for provider in providers] == [1, 1]
    retries = logger.of_type("retry")
    assert all(record["error_type"] != "RateLimitError" for record in retries)


def test_async_parallel_any_failure_details() -> None:
    failing_providers = [
        _AsyncProbeProvider(
            "first",
            delay=0.0,
            failures=[RuntimeError("simulated failure A")],
        ),
        _AsyncProbeProvider(
            "second",
            delay=0.0,
            failures=[RuntimeError("simulated failure B")],
        ),
    ]
    runner = AsyncRunner(
        failing_providers,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="parallel-any-fail", model="parallel-any")

    with pytest.raises(AllFailedError) as exc_info:
        asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.2))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ParallelExecutionError)
    assert cause.failures == [
        {
            "provider": "first",
            "attempt": "1",
            "summary": "RuntimeError: simulated failure A",
        },
        {
            "provider": "second",
            "attempt": "2",
            "summary": "RuntimeError: simulated failure B",
        },
    ]


def test_async_parallel_retry_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    request_any = ProviderRequest(prompt="retry", model="parallel-any")
    clock_any = _FakeClock()
    sleep_calls: list[float] = []
    _patch_runner_sleep(monkeypatch, clock_any, sleep_calls)

    flaky = _AsyncProbeProvider(
        "primary",
        delay=0.0,
        text="ok",
        failures=[RateLimitError("slow"), TimeoutError("later")],
    )
    blocker = _AsyncProbeProvider("secondary", delay=0.0, block=True)
    logger = _CapturingLogger()
    runner_any = AsyncRunner(
        [flaky, blocker],
        logger=logger,
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.25, timeout_next_provider=False),
        ),
    )

    async def _execute_any() -> ProviderResponse:
        result = await runner_any.run_async(request_any, shadow_metrics_path="unused.jsonl")
        assert isinstance(result, ProviderResponse)
        return result

    response = asyncio.run(asyncio.wait_for(_execute_any(), timeout=1))
    assert response.text == "ok:retry"
    assert (
        flaky.invocations,
        flaky.cancelled,
        flaky.finished,
        blocker.cancelled,
        blocker.finished,
    ) == (3, False, True, True, True)
    assert [event["error_type"] for event in logger.of_type("retry")] == [
        "RateLimitError",
        "TimeoutError",
    ]

    flaky_fail = _AsyncProbeProvider(
        "limited",
        delay=0.0,
        text="never",
        failures=[RateLimitError("first"), RateLimitError("second"), RateLimitError("third")],
    )
    runner_fail = AsyncRunner(
        [flaky_fail],
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.1),
            max_attempts=2,
        ),
    )

    async def _execute_fail() -> ProviderResponse:
        result = await runner_fail.run_async(request_any, shadow_metrics_path="unused.jsonl")
        assert isinstance(result, ProviderResponse)
        return result

    with pytest.raises(ParallelExecutionError):
        asyncio.run(asyncio.wait_for(_execute_fail(), timeout=1))

    assert (
        flaky_fail.invocations,
        flaky_fail.cancelled,
        flaky_fail.finished,
    ) == (2, False, True)
    assert sleep_calls == [0.25, 0.1]

    request_all = ProviderRequest(prompt="gather", model="parallel-all")
    _patch_runner_sleep(monkeypatch, _FakeClock())
    fast = _AsyncProbeProvider("fast", delay=0.0, text="fast")
    slow = _AsyncProbeProvider("slow", delay=0.1, text="slow")
    ready = _AsyncProbeProvider("ready", delay=0.0, text="ready")
    logger_all = _CapturingLogger()
    runner_all = AsyncRunner(
        [fast, slow, ready],
        logger=logger_all,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL),
    )

    result = asyncio.run(
        asyncio.wait_for(
            runner_all.run_async(request_all, shadow_metrics_path="unused.jsonl"),
            timeout=0.2,
        )
    )
    assert isinstance(result, ParallelAllResult)
    assert [entry[1].name() for entry in result.invocations] == ["fast", "slow", "ready"]
    assert result.primary_response.text == "fast:gather"
    assert [(p.cancelled, p.finished) for p in (fast, slow, ready)] == [(False, True)] * 3
    assert logger_all.of_type("retry") == []


def test_async_parallel_all_rate_limit_retries() -> None:
    providers = [
        _AsyncProbeProvider("rl_all_a", delay=0.0, failures=[RateLimitError("a")]),
        _AsyncProbeProvider("rl_all_b", delay=0.0, failures=[RateLimitError("b")]),
    ]
    logger = _CapturingLogger()
    runner = AsyncRunner(
        providers,
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL, max_concurrency=2),
    )
    request = ProviderRequest(prompt="rl-all", model="model-parallel-all-rl")

    async def _execute() -> ParallelAllResult[Any, ProviderResponse]:
        result = await runner.run_async(request)
        assert isinstance(result, ParallelAllResult)
        return result

    result = asyncio.run(asyncio.wait_for(_execute(), timeout=0.2))

    assert [response.text for response in result.responses] == [
        f"{provider.name()}:{request.prompt}" for provider in providers
    ]
    assert [provider.invocations for provider in providers] == [2, 2]
    retries = logger.of_type("retry")
    assert len(retries) == 2
    assert all(record["error_type"] == "RateLimitError" for record in retries)
    assert {record["next_attempt"] for record in retries} == {3, 4}
