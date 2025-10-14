from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llm_adapter.errors import RateLimitError
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from llm_adapter.runner import AsyncRunner, ParallelAllResult
from llm_adapter.runner_config import RunnerConfig, RunnerMode

from .conftest import _AsyncProbeProvider, _CapturingLogger, _FakeClock, _patch_runner_sleep


def test_async_parallel_all_retry_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    request = ProviderRequest(prompt="gather", model="parallel-all")
    _patch_runner_sleep(monkeypatch, _FakeClock())
    fast = _AsyncProbeProvider("fast", delay=0.0, text="fast")
    slow = _AsyncProbeProvider("slow", delay=0.1, text="slow")
    ready = _AsyncProbeProvider("ready", delay=0.0, text="ready")
    logger = _CapturingLogger()
    runner = AsyncRunner(
        [fast, slow, ready],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL),
    )

    result = asyncio.run(
        asyncio.wait_for(
            runner.run_async(request, shadow_metrics_path="unused.jsonl"),
            timeout=0.2,
        )
    )
    assert isinstance(result, ParallelAllResult)
    assert [entry[1].name() for entry in result.invocations] == [
        "fast",
        "slow",
        "ready",
    ]
    assert result.primary_response.text == "fast:gather"
    assert [(p.cancelled, p.finished) for p in (fast, slow, ready)] == [(False, True)] * 3
    assert logger.of_type("retry") == []


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
