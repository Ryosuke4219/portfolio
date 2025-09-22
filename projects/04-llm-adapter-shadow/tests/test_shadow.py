import json

from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import Runner
from src.llm_adapter.provider_spi import ProviderRequest


def test_shadow_exec_records_metrics(tmp_path):
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    response = runner.run(
        ProviderRequest(prompt="hello"),
        shadow=shadow,
        shadow_metrics_path=metrics_path,
    )

    assert response.text.startswith("echo(primary):")
    assert metrics_path.exists()

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")
    success_event = next(item for item in payloads if item["event"] == "provider_success")

    assert diff_event["primary_provider"] == "primary"
    assert diff_event["shadow_provider"] == "shadow"
    assert diff_event["shadow_ok"] is True
    assert diff_event["primary_text_len"] == len(response.text)
    assert diff_event["primary_token_usage_total"] == response.token_usage.total
    assert diff_event["request_fingerprint"]

    assert success_event["provider"] == "primary"
    assert success_event["attempt"] == 1
    assert success_event["shadow_used"] is True
    assert success_event["latency_ms"] == response.latency_ms

    expected_tokens = max(1, len("hello") // 4) + 16
    assert diff_event["shadow_token_usage_total"] == expected_tokens
    assert diff_event["shadow_text_len"] == len("echo(shadow): hello")


def test_shadow_error_records_metrics(tmp_path):
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    runner.run(
        ProviderRequest(prompt="[TIMEOUT] hello"),
        shadow=shadow,
        shadow_metrics_path=metrics_path,
    )

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")

    assert diff_event["shadow_ok"] is False
    assert diff_event["shadow_error"] == "TimeoutError"
    assert diff_event["shadow_error_message"] == "simulated timeout"
    assert diff_event["shadow_duration_ms"] >= 0


def test_request_hash_includes_max_tokens(tmp_path):
    provider = MockProvider("primary", base_latency_ms=1, error_markers=set())
    runner = Runner([provider])

    metrics_path = tmp_path / "metrics.jsonl"

    runner.run(
        ProviderRequest(prompt="hello", max_tokens=32),
        shadow_metrics_path=metrics_path,
    )
    runner.run(
        ProviderRequest(prompt="hello", max_tokens=64),
        shadow_metrics_path=metrics_path,
    )

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    success_events = [item for item in payloads if item["event"] == "provider_success"]

    assert len(success_events) == 2
    request_hashes = {event["request_hash"] for event in success_events}
    fingerprints = {event["request_fingerprint"] for event in success_events}

    assert len(request_hashes) == 2
    assert len(fingerprints) == 2
