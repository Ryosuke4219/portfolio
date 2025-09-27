import pytest
from pathlib import Path

import pytest

from src.llm_adapter.errors import TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import Runner
from tests.helpers.fakes import FakeLogger


def _providers_for(marker: str):
    failing = MockProvider("p1", base_latency_ms=5, error_markers={marker})
    fallback = MockProvider("p2", base_latency_ms=5, error_markers=set())
    return failing, fallback


def test_timeout_fallback():
    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    request = ProviderRequest(prompt="[TIMEOUT] hello", model="fallback-model")
    response = runner.run(request)

    assert response.text.startswith("echo(p2):")
    assert response.model == "fallback-model"


def test_ratelimit_retry_fallback():
    p1, p2 = _providers_for("[RATELIMIT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[RATELIMIT] test", model="fallback-model"))
    assert response.text.startswith("echo(p2):")


def test_ratelimit_backoff_sleep(monkeypatch: pytest.MonkeyPatch):
    sleep_calls: list[float] = []

    def fake_runner_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("time.sleep", fake_runner_sleep)

    p1, p2 = _providers_for("[RATELIMIT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[RATELIMIT] backoff", model="fallback-model"))

    assert response.text.startswith("echo(p2):")
    assert sleep_calls.count(0.05) == 1


def test_invalid_json_fallback():
    p1, p2 = _providers_for("[INVALID_JSON]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[INVALID_JSON] test", model="fallback-model"))
    assert response.text.startswith("echo(p2):")


def test_timeout_no_backoff(monkeypatch: pytest.MonkeyPatch):
    sleep_calls: list[float] = []

    def fake_runner_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("time.sleep", fake_runner_sleep)

    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[TIMEOUT] no-wait", model="fallback-model"))

    assert response.text.startswith("echo(p2):")
    assert all(abs(delay - 0.05) > 1e-9 for delay in sleep_calls)


def test_timeout_fallback_records_metrics():
    p1, p2 = _providers_for("[TIMEOUT]")
    logger = FakeLogger()
    metrics_path = "memory://fallback"
    runner = Runner([p1, p2], logger=logger)

    response = runner.run(
        ProviderRequest(prompt="[TIMEOUT] metrics", model="fallback-model"),
        shadow=None,
        shadow_metrics_path=metrics_path,
        logger=logger,
    )

    assert response.text.startswith("echo(p2):")

    target_path = str(Path(metrics_path))
    payloads = [record for _, path, record in logger.events if path == target_path]
    call_events = [item for item in payloads if item["event"] == "provider_call"]
    error_event = next(
        item for item in call_events if item["provider"] == "p1" and item["status"] == "error"
    )
    success_event = next(
        item for item in call_events if item["provider"] == "p2" and item["status"] == "ok"
    )

    assert error_event["provider"] == "p1"
    assert error_event["attempt"] == 1
    assert error_event["error_type"] == "TimeoutError"
    assert error_event["request_fingerprint"]
    assert error_event["latency_ms"] >= 0

    assert success_event["provider"] == "p2"
    assert success_event["attempt"] == 2
    assert success_event["shadow_used"] is False
    assert success_event["tokens_out"] == response.token_usage.completion


def test_runner_emits_chain_failed_metric():
    failing1 = MockProvider("p1", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    failing2 = MockProvider("p2", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    logger = FakeLogger()
    metrics_path = "memory://failure"
    runner = Runner([failing1, failing2], logger=logger)

    with pytest.raises(TimeoutError):
        runner.run(
            ProviderRequest(prompt="[TIMEOUT] hard", model="fallback-model"),
            shadow=None,
            shadow_metrics_path=metrics_path,
            logger=logger,
        )

    target_path = str(Path(metrics_path))
    payloads = [record for _, path, record in logger.events if path == target_path]
    call_events = [item for item in payloads if item["event"] == "provider_call"]
    assert {event["provider"] for event in call_events} == {"p1", "p2"}
    assert all(event["status"] == "error" for event in call_events)

    chain_event = next(item for item in payloads if item["event"] == "provider_chain_failed")
    assert chain_event["provider_attempts"] == 2
    assert chain_event["last_error_type"] == "TimeoutError"
