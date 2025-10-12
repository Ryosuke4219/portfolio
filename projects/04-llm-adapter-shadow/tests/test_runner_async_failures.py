from __future__ import annotations

import asyncio

import pytest
from src.llm_adapter.errors import RetriableError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner_async import AllFailedError, AsyncRunner
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode

from tests.shadow._runner_test_helpers import _ErrorProvider, _SuccessProvider, FakeLogger

pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.mark.asyncio
async def test_all_failed_error_is_raised_and_wrapped() -> None:
    logger = FakeLogger()
    first_error = RetriableError("nope")
    runner = AsyncRunner(
        [
            _ErrorProvider("first", first_error),
            _ErrorProvider("second", RetriableError("still nope")),
        ],
        logger=logger,
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises(AllFailedError) as excinfo:
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    assert isinstance(excinfo.value.__cause__, RetriableError)
    run_event = logger.of_type("run_metric")[0]
    assert run_event["status"] == "error"
    assert run_event["run_id"] == run_event["request_fingerprint"]
    assert run_event["mode"] == "sequential"
    assert run_event["providers"] == ["first", "second"]


@pytest.mark.asyncio
async def test_run_metric_success_includes_extended_metadata() -> None:
    logger = FakeLogger()
    runner = AsyncRunner([_SuccessProvider("primary")], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-model")

    await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    run_event = logger.of_type("run_metric")[0]
    assert run_event["status"] == "ok"
    assert run_event["run_id"] == run_event["request_fingerprint"]
    assert run_event["mode"] == "sequential"
    assert run_event["providers"] == ["primary"]


class _AsyncProbeProvider:
    def __init__(self, name: str, *, delay: float, text: str | None = None) -> None:
        self._name = name
        self._delay = delay
        self._text = text or name
        self.cancelled = False

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
        try:
            if self._delay > 0:
                await asyncio.sleep(self._delay)
            return ProviderResponse(
                text=f"{self._text}:{request.prompt}",
                latency_ms=int(self._delay * 1000),
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_parallel_any_cancelled_logs_exception() -> None:
    fast = _AsyncProbeProvider("fast", delay=0)
    slow = _AsyncProbeProvider("slow", delay=0.2)
    logger = FakeLogger()
    runner = AsyncRunner(
        [fast, slow],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="demo-model")

    response = await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    assert response.text == "fast:hi"
    assert slow.cancelled is True

    provider_events = {event["provider"]: event for event in logger.of_type("provider_call")}
    assert provider_events["fast"]["status"] == "ok"
    slow_event = provider_events["slow"]
    assert slow_event["status"] == "error"
    assert slow_event["error_type"] == "CancelledError"
    assert slow_event["error_family"] == "unknown"

    run_metrics = {
        event["provider"]: event
        for event in logger.of_type("run_metric")
        if event["provider"] is not None
    }
    assert run_metrics["fast"]["status"] == "ok"
    slow_metric = run_metrics["slow"]
    assert slow_metric["status"] == "error"
    assert slow_metric["error_type"] == "CancelledError"
    assert slow_metric["error_family"] == "unknown"
