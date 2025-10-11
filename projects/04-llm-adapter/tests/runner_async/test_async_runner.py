from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from adapter.core.errors import ParallelExecutionError, RateLimitError, RetriableError, TimeoutError
from adapter.core.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from adapter.core import runner_async
from adapter.core.runner_async import AsyncRunner
from adapter.core import runner_api
from adapter.core.runner_config_builder import BackoffPolicy, RunnerConfig, RunnerMode


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for logged, payload in self.events if logged == event_type]


class _ErrorProvider(ProviderSPI):
    def __init__(self, name: str, exc: Exception) -> None:
        self._name = name
        self._exc = exc

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:  # pragma: no cover - static data
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - raises
        raise self._exc


class _SuccessProvider(ProviderSPI):
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:  # pragma: no cover - static data
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(text=f"{self._name}:ok", latency_ms=1, model=request.model)


pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.mark.asyncio
async def test_async_rate_limit_triggers_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    rate_limited = _ErrorProvider("rate-limit", RateLimitError("slow"))
    succeeding = _SuccessProvider("success")
    sleep_calls: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("adapter.core.runner_async.asyncio.sleep", _fake_sleep)

    logger = FakeLogger()
    runner = AsyncRunner(
        [rate_limited, succeeding],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.SEQUENTIAL, backoff=BackoffPolicy(rate_limit_sleep_s=0.25)),
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    response = await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    assert response.text == "success:ok"
    assert sleep_calls == [0.25]
    first_event = logger.of_type("provider_call")[0]
    assert first_event["provider"] == "rate-limit"
    assert first_event["status"] == "error"
    assert first_event["error_type"] == "RateLimitError"
    assert first_event["error_family"] == "rate_limit"


@pytest.mark.asyncio
async def test_async_retryable_error_logs_family() -> None:
    logger = FakeLogger()
    runner = AsyncRunner([
        _ErrorProvider("oops", RetriableError("nope")),
    ], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises(RetriableError):
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    provider_event = logger.of_type("provider_call")[0]
    assert provider_event["error_family"] == "retryable"

    chain_event = logger.of_type("provider_chain_failed")[0]
    assert chain_event["last_error_family"] == "retryable"


@pytest.mark.asyncio
async def test_async_consensus_all_timeout_propagates_original_error() -> None:
    runner = AsyncRunner(
        [
            _ErrorProvider("slow-1", TimeoutError("too slow")),
            _ErrorProvider("slow-2", TimeoutError("way too slow")),
        ],
        config=RunnerConfig(mode=RunnerMode.CONSENSUS, backoff=BackoffPolicy()),
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises((ParallelExecutionError, TimeoutError)):
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")


def test_async_runner_module_reference() -> None:
    assert AsyncRunner is runner_async.AsyncRunner
    assert AsyncRunner.__module__ == "adapter.core.runner_async"


def test_async_runner_is_exported_via_runner_api() -> None:
    assert runner_api.AsyncRunner is AsyncRunner

