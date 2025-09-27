from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner, Runner


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.events if kind == event_type]


def test_async_runner_matches_sync(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    sync_runner = Runner([primary])
    async_runner = AsyncRunner([primary])

    sync_request = ProviderRequest(prompt="hello", metadata={"trace_id": "t1"}, model="primary-model")
    async_request = ProviderRequest(prompt="hello", metadata={"trace_id": "t1"}, model="primary-model")

    sync_metrics = tmp_path / "sync-metrics.jsonl"
    async_metrics = tmp_path / "async-metrics.jsonl"

    sync_response = sync_runner.run(sync_request, shadow_metrics_path=sync_metrics)
    async_response = asyncio.run(
        async_runner.run_async(async_request, shadow_metrics_path=async_metrics)
    )

    assert async_response.text == sync_response.text
    assert async_response.model == sync_response.model
    assert async_metrics.exists()


def test_async_shadow_exec_uses_injected_logger(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    logger = _CapturingLogger()
    runner = AsyncRunner([primary], logger=logger)

    request = ProviderRequest(prompt="hello", model="primary-model")
    metrics_path = tmp_path / "async-unused.jsonl"

    response = asyncio.run(
        runner.run_async(
            request,
            shadow=shadow,
            shadow_metrics_path=metrics_path,
        )
    )

    diff_events = logger.of_type("shadow_diff")
    assert len(diff_events) == 1
    diff_event = diff_events[0]
    assert diff_event["primary_provider"] == "primary"
    assert diff_event["shadow_provider"] == "shadow"
    assert diff_event["shadow_ok"] is True
    assert diff_event["primary_text_len"] == len(response.text)
    assert not metrics_path.exists()


def test_async_shadow_exec_without_metrics_path_skips_logging() -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    logger = _CapturingLogger()
    runner = AsyncRunner([primary], logger=logger)

    request = ProviderRequest(prompt="hello", model="primary-model")

    asyncio.run(
        runner.run_async(
            request,
            shadow=shadow,
            shadow_metrics_path=None,
        )
    )

    assert logger.of_type("shadow_diff") == []


def test_async_shadow_exec_records_metrics(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    runner = AsyncRunner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    metadata = {"trace_id": "trace-async", "project_id": "proj-async"}
    request = ProviderRequest(prompt="hello", metadata=metadata, model="primary-model")

    response = asyncio.run(
        runner.run_async(
            request,
            shadow=shadow,
            shadow_metrics_path=metrics_path,
        )
    )

    assert response.text.startswith("echo(primary):")
    assert metrics_path.exists()

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")
    call_event = next(item for item in payloads if item["event"] == "provider_call")

    assert diff_event["primary_provider"] == "primary"
    assert diff_event["shadow_provider"] == "shadow"
    assert diff_event["shadow_ok"] is True
    token_usage = response.token_usage
    assert token_usage is not None
    assert diff_event["primary_token_usage_total"] == token_usage.total
    expected_tokens = max(1, len("hello") // 4) + 16
    assert diff_event["shadow_token_usage_total"] == expected_tokens
    assert diff_event["shadow_text_len"] == len("echo(shadow): hello")
    assert diff_event["request_fingerprint"]
    assert call_event["provider"] == "primary"
    assert call_event["shadow_used"] is True
    assert call_event["status"] == "ok"
    assert call_event["latency_ms"] == response.latency_ms
    assert call_event["tokens_in"] == token_usage.prompt
    assert call_event["tokens_out"] == token_usage.completion
    assert call_event["trace_id"] == metadata["trace_id"]
    assert call_event["project_id"] == metadata["project_id"]


def test_async_shadow_error_records_metrics(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = AsyncRunner([primary])

    metrics_path = tmp_path / "metrics-error.jsonl"

    asyncio.run(
        runner.run_async(
            ProviderRequest(prompt="[TIMEOUT] hello", model="primary-model"),
            shadow=shadow,
            shadow_metrics_path=metrics_path,
        )
    )

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")

    assert diff_event["shadow_ok"] is False
    assert diff_event["shadow_error"] == "TimeoutError"
    assert diff_event["shadow_error_message"] == "simulated timeout"
    assert diff_event["shadow_duration_ms"] >= 0
