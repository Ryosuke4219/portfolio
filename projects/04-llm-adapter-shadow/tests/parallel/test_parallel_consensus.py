from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from llm_adapter.parallel_exec import (
    ParallelExecutionError,
    run_parallel_any_sync,
)
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from llm_adapter.providers.mock import MockProvider
from llm_adapter.runner import Runner
from llm_adapter.runner_config import RunnerConfig, RunnerMode
from llm_adapter.runner_parallel.consensus import (
    _normalize_candidate_text,
    compute_consensus,
    ConsensusConfig,
)
from llm_adapter.shadow import run_with_shadow

from ..parallel_helpers import _StaticProvider

# --- コンセンサス/シャドー計測 ---


def test_compute_consensus_majority_vote() -> None:
    responses = [
        ProviderResponse("A", 0),
        ProviderResponse("A", 0),
        ProviderResponse("B", 0),
    ]
    result = compute_consensus(responses, config=ConsensusConfig(quorum=2))
    assert result.response.text == "A"
    assert result.votes == 2
    with pytest.raises(ParallelExecutionError):
        compute_consensus(responses, config=ConsensusConfig(quorum=3))


def test_compute_consensus_accepts_numeric_scores() -> None:
    responses = [
        ProviderResponse(text="int", latency_ms=0, raw={"score": 1}),
        ProviderResponse(text="float", latency_ms=0, raw={"score": 1.5}),
    ]

    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="weighted", quorum=1),
    )

    assert result.response.text == "float"
    assert result.scores == {"int": 1.0, "float": 1.5}


def test_compute_consensus_records_schema_failures_and_applies_tie_breaker() -> None:
    schema = json.dumps({"type": "object", "required": ["answer"]})
    responses = [
        ProviderResponse(
            text=json.dumps({"answer": "slow"}),
            latency_ms=20,
        ),
        ProviderResponse(
            text=json.dumps({"answer": "fast"}),
            latency_ms=10,
        ),
        ProviderResponse(text="oops", latency_ms=1),
    ]

    result = compute_consensus(
        responses,
        config=ConsensusConfig(schema=schema, tie_breaker="latency", quorum=1),
    )

    assert result.response.text == json.dumps({"answer": "fast"})
    assert result.tie_break_applied is True
    assert result.tie_breaker_selected == "latency"
    assert result.tie_break_reason == "latency(min=10)"
    assert result.abstained == 1
    assert result.schema_checked is True
    assert result.schema_failures == {2: "invalid json: Expecting value"}


def test_normalize_candidate_text_for_strings() -> None:
    normalized_a, display_a = _normalize_candidate_text(" Foo   Bar ")
    normalized_b, display_b = _normalize_candidate_text("foo bar")
    normalized_c, _ = _normalize_candidate_text("Foo baz")

    assert normalized_a == normalized_b
    assert normalized_a != normalized_c
    assert display_a == "Foo   Bar"
    assert display_b == "foo bar"


def test_normalize_candidate_text_for_json_payloads() -> None:
    normalized_a, _ = _normalize_candidate_text('{"b":[2,3],"a":1}')
    normalized_b, display_b = _normalize_candidate_text('{ "a" : 1, "b" : [2,3] }')
    normalized_c, _ = _normalize_candidate_text('{"a":2,"b":[2,3]}')

    assert normalized_a == normalized_b
    assert normalized_a != normalized_c
    assert display_b == '{ "a" : 1, "b" : [2,3] }'


def test_parallel_any_with_shadow_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_adapter.providers.mock.random.random", lambda: 0.0)
    failing = MockProvider("fail", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    primary = MockProvider("primary", base_latency_ms=1, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    fail_request = ProviderRequest(prompt="[TIMEOUT] fail", model="m")
    success_request = ProviderRequest(prompt="[TIMEOUT] ok", model="m")
    metrics_path = tmp_path / "parallel.jsonl"

    def fail_worker() -> ProviderResponse:
        return failing.invoke(fail_request)

    def success_worker() -> ProviderResponse:
        result = run_with_shadow(
            primary,
            shadow,
            success_request,
            metrics_path=metrics_path,
        )
        if isinstance(result, tuple):
            return result[0]
        return cast(ProviderResponse, result)

    response = run_parallel_any_sync((fail_worker, success_worker))
    assert response.text.startswith("echo(primary):")
    payloads = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]
    shadow_event = next(item for item in payloads if item["event"] == "shadow_diff")
    assert shadow_event["shadow_provider"] == "shadow"
    assert shadow_event["shadow_ok"] is False
    assert shadow_event["shadow_error"] == "TimeoutError"


def test_consensus_vote_event_and_shadow_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_adapter.providers.mock.random.random", lambda: 0.0)

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
    assert consensus_event["strategy"] == "majority_vote"
    assert consensus_event["quorum"] == 2
    assert consensus_event["reason"] == "majority_vote quorum=2/3"
    assert consensus_event["voters_total"] == 3
    assert consensus_event["votes_for"] == 2
    assert consensus_event["votes_against"] == 1
    assert consensus_event["winner_provider"] == "agree_a"
    assert consensus_event["chosen_provider"] == "agree_a"
    assert consensus_event["winner_latency_ms"] == response.latency_ms
    assert consensus_event["votes"][response.text] == 2
    summaries = consensus_event["candidate_summaries"]
    assert {entry["provider"] for entry in summaries} == {
        "agree_a",
        "agree_b",
        "disagree",
    }

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
    assert (
        winner_diff["shadow_consensus_delta"]["reason"]
        == "majority_vote quorum=2/3"
    )

