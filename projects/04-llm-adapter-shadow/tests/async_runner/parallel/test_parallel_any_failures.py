from __future__ import annotations

import asyncio

import pytest

from llm_adapter.errors import RateLimitError, TimeoutError
from llm_adapter.parallel_exec import ParallelExecutionError
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from llm_adapter.runner import AsyncRunner
from llm_adapter.runner_async import AllFailedError
from llm_adapter.runner_config import BackoffPolicy, RunnerConfig, RunnerMode

from .conftest import (
    _AsyncProbeProvider,
    _CapturingLogger,
    _FakeClock,
    _patch_runner_sleep,
)


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


def test_async_parallel_any_retry_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    request = ProviderRequest(prompt="retry", model="parallel-any")
    clock = _FakeClock()
    sleep_calls: list[float] = []
    _patch_runner_sleep(monkeypatch, clock, sleep_calls)

    flaky = _AsyncProbeProvider(
        "primary",
        delay=0.0,
        text="ok",
        failures=[RateLimitError("slow"), TimeoutError("later")],
    )
    blocker = _AsyncProbeProvider("secondary", delay=0.0, block=True)
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [flaky, blocker],
        logger=logger,
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.25, timeout_next_provider=False),
        ),
    )

    async def _execute() -> ProviderResponse:
        result = await runner.run_async(request, shadow_metrics_path="unused.jsonl")
        assert isinstance(result, ProviderResponse)
        return result

    response = asyncio.run(asyncio.wait_for(_execute(), timeout=1))
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
        result = await runner_fail.run_async(request, shadow_metrics_path="unused.jsonl")
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
