from __future__ import annotations

import asyncio

import pytest

from src.llm_adapter.errors import RateLimitError, RetriableError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner import AsyncRunner
from src.llm_adapter.runner_config import (
    BackoffPolicy,
    ConsensusConfig,
    RunnerConfig,
    RunnerMode,
)
from src.llm_adapter.runner_parallel import ParallelExecutionError

from tests.shadow._runner_test_helpers import (
    FakeLogger,
    _ErrorProvider,
    _SuccessProvider,
)


class _SchemaFailingProvider(ProviderSPI):
    def __init__(self, name: str, text: str) -> None:
        self._name = name
        self._text = text

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._text,
            latency_ms=5,
            tokens_in=5,
            tokens_out=5,
            model=request.model,
        )

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return 0.0


@pytest.mark.asyncio
def test_async_rate_limit_triggers_backoff_and_logs(
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

    async def _run() -> None:
        response = await runner.run_async(request, shadow_metrics_path="unused.jsonl")
        assert response.text == "success:ok"

    asyncio.run(_run())

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
def test_async_retryable_error_logs_family() -> None:
    logger = FakeLogger()
    runner = AsyncRunner([_ErrorProvider("oops", RetriableError("nope"))], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-model")

    async def _run() -> None:
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    with pytest.raises(RetriableError):
        asyncio.run(_run())

    provider_event = logger.of_type("provider_call")[0]
    assert provider_event["error_family"] == "retryable"

    chain_event = logger.of_type("provider_chain_failed")[0]
    assert chain_event["last_error_family"] == "retryable"


@pytest.mark.asyncio
def test_async_consensus_propagates_schema_failures() -> None:
    providers = [
        _SchemaFailingProvider("bad-json", "not json"),
        _SchemaFailingProvider("missing-key", '{"foo": 1}'),
    ]
    config = RunnerConfig(
        mode=RunnerMode.CONSENSUS,
        consensus=ConsensusConfig(
            schema='{"type": "object", "required": ["answer"]}'
        ),
    )
    runner = AsyncRunner(providers, config=config)
    request = ProviderRequest(prompt="hello", model="demo-model")

    async def _run() -> None:
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    with pytest.raises(ParallelExecutionError) as excinfo:
        asyncio.run(_run())

    error = excinfo.value
    assert hasattr(error, "failures")
    assert error.failures == [
        {
            "index": 0,
            "attempt": 1,
            "provider": "bad-json",
            "reason": "invalid json: Expecting value",
        },
        {
            "index": 1,
            "attempt": 2,
            "provider": "missing-key",
            "reason": "missing keys: answer",
        },
    ]
    message = str(error)
    assert "bad-json" in message
    assert "missing-key" in message
