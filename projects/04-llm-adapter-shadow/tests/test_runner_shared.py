from __future__ import annotations

from typing import Any

import pytest

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner_shared import log_provider_call


class _DummyEventLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append((name, payload))


class _DummyProvider:
    def name(self) -> str:
        return "dummy"


@pytest.mark.parametrize("status", ["errored", "Errored", "ERRORED"])
def test_log_provider_call_normalizes_error_family_status(status: str) -> None:
    event_logger = _DummyEventLogger()
    provider = _DummyProvider()
    request = ProviderRequest(model="test-model", prompt="hello")

    log_provider_call(
        event_logger,
        request_fingerprint="fingerprint",
        provider=provider,
        request=request,
        attempt=1,
        total_providers=1,
        status=status,
        latency_ms=10,
        tokens_in=1,
        tokens_out=1,
        error=Exception("boom"),
        metadata={},
        shadow_used=False,
    )

    assert event_logger.events, "expected provider_call event to be emitted"
    _, payload = event_logger.events[-1]
    assert payload["outcome"] == "error"
