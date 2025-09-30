from __future__ import annotations

import pytest

from src.llm_adapter.errors import RateLimitError, RetriableError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner import AsyncRunner
from src.llm_adapter.runner_config import BackoffPolicy, RunnerConfig, RunnerMode
from tests.shadow._runner_test_helpers import (
    _ErrorProvider,
    _SuccessProvider,
    FakeLogger,
)

pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.mark.asyncio
async def test_async_rate_limit_triggers_backoff_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rate_limited = _ErrorProvider("rate-limit", RateLimitError("slow down"))
    succeeding = _SuccessProvider("success")

    sleep_calls: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.llm_adapter.runner_async.asyncio.sleep", _fake_sleep)

    logger = FakeLogger()
    runner = AsyncRunner(
        [rate_limited, succeeding],
        logger=logger,
        config=RunnerConfig(backoff=BackoffPolicy(rate_limit_sleep_s=0.321)),
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    response = await runner.run_async(request, shadow_metrics_path="unused.jsonl")
    assert response.text == "success:ok"

    assert sleep_calls == [0.321]
    first_call = next(
        record
        for record in logger.of_type("provider_call")
        if record["provider"] == "rate-limit"
    )
    assert first_call["status"] == "error"
    assert first_call["error_type"] == "RateLimitError"
    assert first_call["error_family"] == "rate_limit"


@pytest.mark.asyncio
async def test_async_retryable_error_logs_family() -> None:
    logger = FakeLogger()
    runner = AsyncRunner([_ErrorProvider("oops", RetriableError("nope"))], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises(RetriableError):
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    provider_event = logger.of_type("provider_call")[0]
    assert provider_event["error_family"] == "retryable"

    chain_event = logger.of_type("provider_chain_failed")[0]
    assert chain_event["last_error_family"] == "retryable"


@pytest.mark.asyncio
async def test_async_consensus_all_timeout_propagates_original_error() -> None:
    providers = [
        _ErrorProvider("slow-1", TimeoutError("too slow")),
        _ErrorProvider("slow-2", TimeoutError("way too slow")),
    ]
    runner = AsyncRunner(
        providers,
        config=RunnerConfig(mode=RunnerMode.CONSENSUS),
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises((ParallelExecutionError, TimeoutError)):
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")
