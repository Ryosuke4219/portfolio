from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from src.llm_adapter.provider_spi import (
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
)
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner, Runner
from src.llm_adapter.runner_config import ConsensusConfig, RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import ParallelExecutionError


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.events if kind == event_type]


class _AsyncProbeProvider:
    def __init__(self, name: str, *, delay: float, text: str | None = None) -> None:
        self._name = name
        self._delay = delay
        self._text = text or name
        self.cancelled = False
        self.finished = False

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
        try:
            await asyncio.sleep(self._delay)
            return ProviderResponse(
                text=f"{self._text}:{request.prompt}",
                latency_ms=int(self._delay * 1000),
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished = True


class _StaticProvider:
    def __init__(self, name: str, text: str, latency_ms: int) -> None:
        self._name = name
        self._text = text
        self._latency_ms = latency_ms

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._text,
            latency_ms=self._latency_ms,
            token_usage=TokenUsage(prompt=1, completion=1),
            model=request.model,
            finish_reason="stop",
        )


def test_async_runner_respects_rpm_spacing() -> None:
    call_times: list[float] = []

    class _RecordingProvider:
        def name(self) -> str:
            return "async-rate"

        def capabilities(self) -> set[str]:
            return set()

        async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
            call_times.append(time.monotonic())
            await asyncio.sleep(0)
            return ProviderResponse(
                text="ok",
                latency_ms=1,
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
            )

    provider = _RecordingProvider()
    runner = AsyncRunner([provider], config=RunnerConfig(rpm=120))
    request = ProviderRequest(prompt="hello", model="primary-model")

    async def _run_calls() -> None:
        for _ in range(3):
            await runner.run_async(request)

    asyncio.run(_run_calls())

    assert len(call_times) == 3
    first_interval = call_times[1] - call_times[0]
    second_interval = call_times[2] - call_times[1]
    expected_interval = 60.0 / 120

    assert first_interval < expected_interval / 2
    assert abs(second_interval - expected_interval) <= 0.15


def test_async_runner_matches_sync(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    sync_runner = Runner([primary])
    async_runner = AsyncRunner([primary])

    sync_request = ProviderRequest(
        prompt="hello",
        metadata={"trace_id": "t1"},
        model="primary-model",
    )
    async_request = ProviderRequest(
        prompt="hello",
        metadata={"trace_id": "t1"},
        model="primary-model",
    )

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


def test_async_consensus_vote_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)

    agree_text = "agree: async"
    agree_a = _StaticProvider("agree_a", agree_text, latency_ms=5)
    agree_b = _StaticProvider("agree_b", agree_text, latency_ms=7)
    disagree = _StaticProvider("disagree", "disagree: async", latency_ms=9)
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers=set())

    runner = AsyncRunner(
        [agree_a, agree_b, disagree],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )

    request = ProviderRequest(prompt="async hello", model="m-async-consensus")
    metrics_path = tmp_path / "async-consensus.jsonl"

    response = asyncio.run(
        runner.run_async(
            request,
            shadow=shadow,
            shadow_metrics_path=metrics_path,
        )
    )

    assert response.text == agree_text
    payloads = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]
    consensus_event = next(
        item for item in payloads if item.get("event") == "consensus_vote"
    )
    assert consensus_event["votes_for"] == 2
    assert consensus_event["votes_against"] == 1
    assert consensus_event["winner_provider"] == "agree_a"

    winner_diff = next(
        item
        for item in payloads
        if item.get("event") == "shadow_diff"
        and item.get("primary_provider") == "agree_a"
    )
    assert winner_diff["shadow_consensus_delta"]["votes_total"] == 3


def test_async_parallel_any_returns_first_completion() -> None:
    slow = _AsyncProbeProvider("slow", delay=0.1, text="slow")
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    runner = AsyncRunner(
        [slow, fast],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="model-parallel-any")

    response = asyncio.run(runner.run_async(request))

    assert response.text.startswith("fast:")


def test_async_parallel_any_cancellation_waits_for_cleanup() -> None:
    slow = _AsyncProbeProvider("slow", delay=0.2, text="slow")
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    runner = AsyncRunner(
        [slow, fast],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="model-parallel-cancel")

    response = asyncio.run(runner.run_async(request))

    assert response.text.startswith("fast:")
    assert slow.cancelled is True
    assert slow.finished is True


def test_async_consensus_quorum_failure() -> None:
    provider_a = _AsyncProbeProvider("pa", delay=0.01, text="A")
    provider_b = _AsyncProbeProvider("pb", delay=0.01, text="B")
    runner = AsyncRunner(
        [provider_a, provider_b],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            consensus=ConsensusConfig(quorum=2),
        ),
    )
    request = ProviderRequest(prompt="topic", model="model-consensus")

    with pytest.raises(ParallelExecutionError):
        asyncio.run(runner.run_async(request))
