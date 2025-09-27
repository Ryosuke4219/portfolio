from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner, BackoffPolicy, Runner, RunnerConfig


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


def test_async_runner_custom_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    ratelimited = MockProvider("p1", base_latency_ms=5, error_markers={"[RATELIMIT]"})
    fallback = MockProvider("p2", base_latency_ms=5, error_markers=set())
    runner = AsyncRunner(
        [ratelimited, fallback],
        config=RunnerConfig(backoff=BackoffPolicy(rate_limit_seconds=0.02)),
    )

    response = asyncio.run(
        runner.run_async(ProviderRequest(prompt="[RATELIMIT] async", model="fallback-model"))
    )

    assert response.text.startswith("echo(p2):")
    assert sleep_calls == [pytest.approx(0.02)]
