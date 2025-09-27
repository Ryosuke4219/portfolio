from __future__ import annotations

from pathlib import Path

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import Runner
from tests.helpers.fakes import FakeLogger


def test_shadow_exec_records_metrics() -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    logger = FakeLogger()
    runner = Runner([primary], logger=logger)

    metrics_path = "memory://shadow-success"
    metadata = {"trace_id": "trace-123", "project_id": "proj-789"}

    # モデル名は明示指定（フォールバック禁止の設計に合わせる）
    request = ProviderRequest(prompt="hello", metadata=metadata, model="primary-model")
    response = runner.run(
        request,
        shadow=shadow,
        shadow_metrics_path=metrics_path,
        logger=logger,
    )

    assert response.text.startswith("echo(primary):")
    assert response.model == "primary-model"
    target_path = str(Path(metrics_path))
    payloads = [record for _, path, record in logger.events if path == target_path]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")
    call_event = next(item for item in payloads if item["event"] == "provider_call")

    assert diff_event["primary_provider"] == "primary"
    assert diff_event["shadow_provider"] == "shadow"
    assert diff_event["shadow_ok"] is True
    assert diff_event["primary_text_len"] == len(response.text)
    token_usage = response.token_usage
    assert token_usage is not None

    assert diff_event["primary_token_usage_total"] == token_usage.total
    assert diff_event["request_fingerprint"]

    assert call_event["provider"] == "primary"
    assert call_event["attempt"] == 1
    assert call_event["shadow_used"] is True
    assert call_event["status"] == "ok"
    assert call_event["latency_ms"] == response.latency_ms
    assert call_event["tokens_in"] == token_usage.prompt
    assert call_event["tokens_out"] == token_usage.completion
    assert call_event["trace_id"] == metadata["trace_id"]
    assert call_event["project_id"] == metadata["project_id"]
    # メトリクスに model は記録しない設計（プライバシー配慮）
    assert call_event.get("model") is None

    expected_tokens = max(1, len("hello") // 4) + 16
    assert diff_event["shadow_token_usage_total"] == expected_tokens
    assert diff_event["shadow_text_len"] == len("echo(shadow): hello")


def test_shadow_error_records_metrics() -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    logger = FakeLogger()
    runner = Runner([primary], logger=logger)

    metrics_path = "memory://shadow-error"
    runner.run(
        ProviderRequest(prompt="[TIMEOUT] hello", model="primary-model"),
        shadow=shadow,
        shadow_metrics_path=metrics_path,
        logger=logger,
    )

    target_path = str(Path(metrics_path))
    payloads = [record for _, path, record in logger.events if path == target_path]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")

    assert diff_event["shadow_ok"] is False
    assert diff_event["shadow_error"] == "TimeoutError"
    assert diff_event["shadow_error_message"] == "simulated timeout"
    assert diff_event["shadow_duration_ms"] >= 0


def test_request_hash_includes_max_tokens() -> None:
    provider = MockProvider("primary", base_latency_ms=1, error_markers=set())
    logger = FakeLogger()
    runner = Runner([provider], logger=logger)

    metrics_path = "memory://shadow-hash"

    runner.run(
        ProviderRequest(prompt="hello", max_tokens=32, model="primary-model"),
        shadow_metrics_path=metrics_path,
        logger=logger,
    )
    runner.run(
        ProviderRequest(prompt="hello", max_tokens=64, model="primary-model"),
        shadow_metrics_path=metrics_path,
        logger=logger,
    )

    target_path = str(Path(metrics_path))
    payloads = [record for _, path, record in logger.events if path == target_path]
    success_events = [
        item
        for item in payloads
        if item["event"] == "provider_call" and item["status"] == "ok"
    ]

    assert len(success_events) == 2
    request_hashes = {event["request_hash"] for event in success_events}
    fingerprints = {event["request_fingerprint"] for event in success_events}

    assert len(request_hashes) == 2
    assert len(fingerprints) == 2
