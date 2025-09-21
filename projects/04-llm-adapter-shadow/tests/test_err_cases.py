import json

import pytest

from src.llm_adapter.errors import TimeoutError
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import Runner
from src.llm_adapter.provider_spi import ProviderRequest


def _providers_for(marker: str):
    failing = MockProvider("p1", base_latency_ms=5, error_markers={marker})
    fallback = MockProvider("p2", base_latency_ms=5, error_markers=set())
    return failing, fallback


def _read_metrics(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_timeout_fallback():
    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[TIMEOUT] hello"))
    assert response.text.startswith("echo(p2):")


def test_ratelimit_retry_fallback():
    p1, p2 = _providers_for("[RATELIMIT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[RATELIMIT] test"))
    assert response.text.startswith("echo(p2):")


def test_invalid_json_fallback():
    p1, p2 = _providers_for("[INVALID_JSON]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[INVALID_JSON] test"))
    assert response.text.startswith("echo(p2):")


def test_timeout_fallback_records_metrics(tmp_path):
    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    metrics_path = tmp_path / "fallback.jsonl"
    response = runner.run(
        ProviderRequest(prompt="[TIMEOUT] metrics"),
        shadow=None,
        shadow_metrics_path=metrics_path,
    )

    assert response.text.startswith("echo(p2):")

    payloads = _read_metrics(metrics_path)
    error_event = next(item for item in payloads if item["event"] == "provider_error")
    success_event = next(item for item in payloads if item["event"] == "provider_success")

    assert error_event["provider"] == "p1"
    assert error_event["attempt"] == 1
    assert error_event["error_type"] == "TimeoutError"
    assert error_event["request_fingerprint"]

    assert success_event["provider"] == "p2"
    assert success_event["attempt"] == 2
    assert success_event["shadow_used"] is False


def test_runner_emits_chain_failed_metric(tmp_path):
    failing1 = MockProvider("p1", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    failing2 = MockProvider("p2", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = Runner([failing1, failing2])

    metrics_path = tmp_path / "failure.jsonl"

    with pytest.raises(TimeoutError):
        runner.run(
            ProviderRequest(prompt="[TIMEOUT] hard"),
            shadow=None,
            shadow_metrics_path=metrics_path,
        )

    payloads = _read_metrics(metrics_path)
    error_events = [item for item in payloads if item["event"] == "provider_error"]
    assert {event["provider"] for event in error_events} == {"p1", "p2"}

    chain_event = next(item for item in payloads if item["event"] == "provider_chain_failed")
    assert chain_event["provider_attempts"] == 2
    assert chain_event["last_error_type"] == "TimeoutError"
