from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from src.llm_adapter.observability import EventLogger
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.shadow import ShadowMetrics


class RecorderLogger(EventLogger):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: dict[str, Any]) -> None:  # type: ignore[override]
        self.events.append((event_type, dict(record)))


class StubProvider:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:  # pragma: no cover - protocol compat
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - unused
        raise NotImplementedError

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return 0.0


class FakeMetrics(ShadowMetrics):
    def __init__(self) -> None:
        super().__init__(payload={}, logger=None)
        self.emitted: list[Mapping[str, Any] | None] = []

    def emit(self, extra: Mapping[str, Any] | None = None) -> None:
        self.emitted.append(extra)


@pytest.fixture
def recorder_logger() -> RecorderLogger:
    return RecorderLogger()


@pytest.fixture
def stub_provider_factory() -> Callable[[str], StubProvider]:
    def factory(name: str) -> StubProvider:
        return StubProvider(name)

    return factory


@pytest.fixture
def provider_request() -> ProviderRequest:
    return ProviderRequest(model="gpt", prompt="hi")


@pytest.fixture
def provider_response() -> ProviderResponse:
    return ProviderResponse(
        "ok",
        latency_ms=42,
        token_usage=TokenUsage(prompt=3, completion=5),
    )


@pytest.fixture
def fake_metrics_factory() -> Callable[[], FakeMetrics]:
    return FakeMetrics
