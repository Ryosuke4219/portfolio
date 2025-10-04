from __future__ import annotations

from typing import Any

import pytest

from src.llm_adapter.errors import ProviderSkip
from src.llm_adapter.observability import EventLogger
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner_shared import log_provider_call, log_run_metric


class _RecordingLogger(EventLogger):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: dict[str, Any]) -> None:  # type: ignore[override]
        self.events.append((event_type, dict(record)))


class _DummyProvider:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


@pytest.fixture()
def provider_request() -> ProviderRequest:
    return ProviderRequest(model="gpt-test", prompt="hello")


@pytest.fixture()
def logger() -> _RecordingLogger:
    return _RecordingLogger()


def test_log_provider_call_normalizes_errored_outcome(
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
        error=None,
        metadata={},
        shadow_used=False,
    )

    event_type, payload = logger.events[-1]
    assert event_type == "provider_call"
    assert payload["status"] == "errored"
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


def test_log_run_metric_normalizes_errored_outcome(
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
        error=None,
        metadata={},
        shadow_used=False,
    )

    event_type, payload = logger.events[-1]
    assert event_type == "run_metric"
    assert payload["status"] == "errored"
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
