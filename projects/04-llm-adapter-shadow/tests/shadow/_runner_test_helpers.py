from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pytest
from src.llm_adapter.errors import ProviderSkip
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner import ParallelAllResult, Runner
from src.llm_adapter.runner_config import RunnerConfig
from src.llm_adapter.runner_sync import ProviderInvocationResult


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [record for logged_event, record in self.events if logged_event == event_type]


class _ErrorProvider(ProviderSPI):
    def __init__(self, name: str, exc: Exception) -> None:
        self._name = name
        self._exc = exc

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - raises
        raise self._exc


class _SuccessProvider(ProviderSPI):
    def __init__(
        self,
        name: str,
        *,
        tokens_in: int = 12,
        tokens_out: int = 8,
        latency_ms: int = 5,
        cost_usd: float = 0.123,
    ) -> None:
        self._name = name
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._latency = latency_ms
        self._cost = cost_usd
        self.cost_calls: list[tuple[int, int]] = []

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=f"{self._name}:ok",
            latency_ms=self._latency,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            model=request.model,
        )

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        self.cost_calls.append((tokens_in, tokens_out))
        return self._cost


class _SkipProvider(ProviderSPI):
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - raises
        raise ProviderSkip(f"{self._name} unavailable")


def _run_and_collect(
    providers: Iterable[ProviderSPI],
    *,
    prompt: str = "hello",
    expect_exception: type[Exception] | None = None,
    config: RunnerConfig | None = None,
) -> tuple[
    ProviderResponse
    | ParallelAllResult[ProviderInvocationResult, ProviderResponse]
    | None,
    FakeLogger,
]:
    logger = FakeLogger()
    runner = Runner(list(providers), logger=logger, config=config)
    request = ProviderRequest(prompt=prompt, model="demo-model")

    metrics_path = "unused-metrics.jsonl"

    if expect_exception is None:
        response = runner.run(request, shadow_metrics_path=metrics_path)
        if isinstance(response, ParallelAllResult):
            return response, logger
        assert isinstance(response, ProviderResponse)
        return response, logger

    with pytest.raises(expect_exception):
        runner.run(request, shadow_metrics_path=metrics_path)
    return None, logger
