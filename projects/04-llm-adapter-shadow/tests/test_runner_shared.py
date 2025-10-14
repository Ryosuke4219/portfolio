from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from llm_adapter.errors import ProviderSkip
from llm_adapter.observability import EventLogger
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from llm_adapter.runner_shared import log_provider_call, log_run_metric


class _RecordingLogger(EventLogger):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))


class _DummyProvider:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - unused
        return ProviderResponse(
            "unused",
            latency_ms=0,
            token_usage=TokenUsage(prompt=0, completion=0),
        )

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return 0.0


@pytest.fixture()
def provider_request() -> ProviderRequest:
    return ProviderRequest(model="gpt-test", prompt="hello")


@pytest.fixture()
def logger() -> _RecordingLogger:
    return _RecordingLogger()


@pytest.mark.parametrize("status", ["errored", "fail", "failed"])
def test_log_provider_call_normalizes_error_family_outcome(
    logger: _RecordingLogger, provider_request: ProviderRequest, status: str
) -> None:
    provider = _DummyProvider("dummy")

    log_provider_call(
        logger,
        request_fingerprint="fingerprint",
        provider=provider,
        request=provider_request,
        attempt=1,
        total_providers=1,
        status=status,
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        error=None,
        metadata={},
        shadow_used=False,
    )

    event_type, payload = logger.events[-1]
    assert event_type == "provider_call"
    assert payload["status"] == status
    assert payload["outcome"] == "error"


@pytest.mark.parametrize("status", ["failed", "fail"])
def test_log_provider_call_normalizes_failed_status(
    status: str, logger: _RecordingLogger, provider_request: ProviderRequest
) -> None:
    provider = _DummyProvider("dummy")

    log_provider_call(
        logger,
        request_fingerprint="fingerprint",
        provider=provider,
        request=provider_request,
        attempt=1,
        total_providers=1,
        status=status,
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        error=None,
        metadata={},
        shadow_used=False,
    )

    _, payload = logger.events[-1]
    assert payload["status"] == status
    assert payload["outcome"] == "error"


def test_log_provider_call_records_skip_outcome_from_skip_error(
    logger: _RecordingLogger, provider_request: ProviderRequest
) -> None:
    provider = _DummyProvider("dummy")

    log_provider_call(
        logger,
        request_fingerprint="fingerprint",
        provider=provider,
        request=provider_request,
        attempt=1,
        total_providers=1,
        status="errored",
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        error=ProviderSkip("skip"),
        metadata={},
        shadow_used=False,
    )

    _, payload = logger.events[-1]
    assert payload["status"] == "errored"
    assert payload["outcome"] == "skip"


@pytest.mark.parametrize("status", ["errored", "fail", "failed"])
def test_log_run_metric_normalizes_error_family_outcome(
    logger: _RecordingLogger, provider_request: ProviderRequest, status: str
) -> None:
    log_run_metric(
        logger,
        request_fingerprint="fingerprint",
        request=provider_request,
        provider=_DummyProvider("dummy"),
        status=status,
        attempts=1,
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.5,
        error=None,
        metadata={},
        shadow_used=False,
    )

    event_type, payload = logger.events[-1]
    assert event_type == "run_metric"
    assert payload["status"] == status
    assert payload["outcome"] == "error"


def test_log_run_metric_records_skip_outcome_from_skip_error(
    logger: _RecordingLogger, provider_request: ProviderRequest
) -> None:
    log_run_metric(
        logger,
        request_fingerprint="fingerprint",
        request=provider_request,
        provider=_DummyProvider("dummy"),
        status="errored",
        attempts=1,
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.5,
        error=ProviderSkip("skip"),
        metadata={},
        shadow_used=False,
    )

    _, payload = logger.events[-1]
    assert payload["status"] == "errored"
    assert payload["outcome"] == "skip"


def test_log_provider_call_includes_shadow_metadata(
    logger: _RecordingLogger, provider_request: ProviderRequest
) -> None:
    provider = _DummyProvider("dummy")

    log_provider_call(
        logger,
        request_fingerprint="fingerprint",
        provider=provider,
        request=provider_request,
        attempt=1,
        total_providers=1,
        status="ok",
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        error=None,
        metadata={
            "shadow": {
                "latency_ms": 456,
                "duration_ms": 789,
                "outcome": "success",
            }
        },
        shadow_used=True,
    )

    _, payload = logger.events[-1]
    assert payload["shadow_latency_ms"] == 456
    assert payload["shadow_duration_ms"] == 789
    assert payload["shadow_outcome"] == "success"


def test_log_provider_call_records_retries(
    logger: _RecordingLogger, provider_request: ProviderRequest
) -> None:
    provider = _DummyProvider("dummy")

    log_provider_call(
        logger,
        request_fingerprint="fingerprint",
        provider=provider,
        request=provider_request,
        attempt=3,
        total_providers=1,
        status="ok",
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        error=None,
        metadata={},
        shadow_used=False,
    )

    _, payload = logger.events[-1]
    assert payload["retries"] == 2


def test_log_run_metric_includes_shadow_metadata(
    logger: _RecordingLogger, provider_request: ProviderRequest
) -> None:
    log_run_metric(
        logger,
        request_fingerprint="fingerprint",
        request=provider_request,
        provider=_DummyProvider("dummy"),
        status="ok",
        attempts=1,
        latency_ms=123,
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.5,
        error=None,
        metadata={
            "shadow": {
                "latency_ms": 456,
                "duration_ms": 789,
                "outcome": "success",
            }
        },
        shadow_used=True,
    )

    _, payload = logger.events[-1]
    assert payload["shadow_latency_ms"] == 456
    assert payload["shadow_duration_ms"] == 789
    assert payload["shadow_outcome"] == "success"
