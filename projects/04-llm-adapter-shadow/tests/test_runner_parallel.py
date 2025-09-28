from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import (
    ConsensusConfig,
    ParallelExecutionError,
    compute_consensus,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from src.llm_adapter.runner_sync import Runner
from src.llm_adapter.shadow import run_with_shadow


class _StaticProvider:
    def __init__(self, name: str, text: str, latency_ms: int) -> None:
        self._name = name
        self._text = text
        self.latency_ms = latency_ms

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._text,
            latency_ms=self.latency_ms,
            token_usage=TokenUsage(prompt=1, completion=1),
            model=request.model,
            finish_reason="stop",
        )


def test_parallel_primitives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)
    failing = MockProvider("fail", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    fast = MockProvider("fast", base_latency_ms=1, error_markers=set())
    fail_request = ProviderRequest(prompt="[TIMEOUT] hi", model="m1")
    ok_request = ProviderRequest(prompt="hi", model="m2")
    winner = run_parallel_any_sync(
        (
            lambda: failing.invoke(fail_request),
            lambda: fast.invoke(ok_request),
        )
    )
    assert winner.text.startswith("echo(fast):")
    request = ProviderRequest(prompt="hello", model="m")
    providers = [
        MockProvider("p1", base_latency_ms=1, error_markers=set()),
        MockProvider("p2", base_latency_ms=2, error_markers=set()),
    ]
    collected = run_parallel_all_sync(tuple(lambda p=p: p.invoke(request) for p in providers))
    assert [res.text for res in collected] == ["echo(p1): hello", "echo(p2): hello"]
    responses = [ProviderResponse("A", 0), ProviderResponse("A", 0), ProviderResponse("B", 0)]
    result = compute_consensus(responses, config=ConsensusConfig(quorum=2))
    assert result.response.text == "A"
    assert result.votes == 2
    with pytest.raises(ParallelExecutionError):
        compute_consensus(responses, config=ConsensusConfig(quorum=3))


def test_parallel_any_with_shadow_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)
    failing = MockProvider("fail", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    primary = MockProvider("primary", base_latency_ms=1, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    fail_request = ProviderRequest(prompt="[TIMEOUT] fail", model="m")
    success_request = ProviderRequest(prompt="[TIMEOUT] ok", model="m")
    metrics_path = tmp_path / "parallel.jsonl"

    def fail_worker() -> ProviderResponse:
        return failing.invoke(fail_request)

    def success_worker() -> ProviderResponse:
        return run_with_shadow(
            primary,
            shadow,
            success_request,
            metrics_path=metrics_path,
        )

    response = run_parallel_any_sync((fail_worker, success_worker))
    assert response.text.startswith("echo(primary):")
    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    shadow_event = next(item for item in payloads if item["event"] == "shadow_diff")
    assert shadow_event["shadow_provider"] == "shadow"
    assert shadow_event["shadow_ok"] is False
    assert shadow_event["shadow_error"] == "TimeoutError"


def test_consensus_vote_event_and_shadow_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)

    agree_text = "agree: hello"
    agree_a = _StaticProvider("agree_a", agree_text, latency_ms=5)
    agree_b = _StaticProvider("agree_b", agree_text, latency_ms=7)
    disagree = _StaticProvider("disagree", "disagree: hello", latency_ms=9)
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers=set())

    runner = Runner(
        [agree_a, agree_b, disagree],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )

    request = ProviderRequest(prompt="hello", model="m-consensus")
    metrics_path = tmp_path / "consensus.jsonl"

    response = runner.run(
        request,
        shadow=shadow,
        shadow_metrics_path=metrics_path,
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
    assert consensus_event["strategy"] == "majority"
    assert consensus_event["voters_total"] == 3
    assert consensus_event["votes_for"] == 2
    assert consensus_event["votes_against"] == 1
    assert consensus_event["winner_provider"] == "agree_a"
    assert consensus_event["winner_latency_ms"] == response.latency_ms
    assert consensus_event["votes"][response.text] == 2
    summaries = consensus_event["candidate_summaries"]
    assert {entry["provider"] for entry in summaries} == {"agree_a", "agree_b", "disagree"}

    run_metric_events = {
        item["provider"]: item["latency_ms"]
        for item in payloads
        if item.get("event") == "run_metric" and item.get("provider") is not None
    }
    expected_latencies = {
        agree_a.name(): agree_a.latency_ms,
        agree_b.name(): agree_b.latency_ms,
        disagree.name(): disagree.latency_ms,
    }
    assert run_metric_events == expected_latencies

    winner_diff = next(
        item
        for item in payloads
        if item.get("event") == "shadow_diff"
        and item.get("primary_provider") == "agree_a"
    )
    assert winner_diff["shadow_consensus_delta"]["votes_for"] == 2
    assert winner_diff["shadow_consensus_delta"]["votes_total"] == 3
