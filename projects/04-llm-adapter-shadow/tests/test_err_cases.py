import json
from pathlib import Path
from typing import Any

import pytest

from src.llm_adapter.errors import TimeoutError
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import Runner
from src.llm_adapter.provider_spi import ProviderRequest


def _providers_for(marker: str):
    failing = MockProvider("p1", base_latency_ms=5, error_markers={marker})
    fallback = MockProvider("p2", base_latency_ms=5, error_markers=set())
    return failing, fallback


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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


def test_invalid_json_fallback():
    p1, p2 = _providers_for("[INVALID_JSON]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[INVALID_JSON] test", model="fallback-model"))
    assert response.text.startswith("echo(p2):")


def test_timeout_fallback_records_metrics(tmp_path: Path):
    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    metrics_path = tmp_path / "fallback.jsonl"
    response = runner.run(
        ProviderRequest(prompt="[TIMEOUT] metrics", model="fallback-model"),
        shadow=None,
        shadow_metrics_path=metrics_path,
    )

    assert response.text.startswith("echo(p2):")

    payloads = _read_metrics(metrics_path)
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


def test_runner_emits_chain_failed_metric(tmp_path: Path):
    failing1 = MockProvider("p1", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    failing2 = MockProvider("p2", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = Runner([failing1, failing2])

    metrics_path = tmp_path / "failure.jsonl"

    with pytest.raises(TimeoutError):
        runner.run(
            ProviderRequest(prompt="[TIMEOUT] hard", model="fallback-model"),
            shadow=None,
            shadow_metrics_path=metrics_path,
        )

    payloads = _read_metrics(metrics_path)
    call_events = [item for item in payloads if item["event"] == "provider_call"]
    assert {event["provider"] for event in call_events} == {"p1", "p2"}
    assert all(event["status"] == "error" for event in call_events)

    chain_event = next(item for item in payloads if item["event"] == "provider_chain_failed")
    assert chain_event["provider_attempts"] == 2
    assert chain_event["last_error_type"] == "TimeoutError"
