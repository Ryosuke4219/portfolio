from __future__ import annotations

from src.llm_adapter.consensus_candidates import (
    CandidateSet,
    _apply_tie_breaker,
    validate_consensus_schema,
)


def test_candidate_set_from_observations_tracks_scores(make_observation):
    observations = [
        make_observation("a", " yes ", latency=120, tokens_in=5, tokens_out=7),
        make_observation("b", "YES", latency=80, tokens_in=3, tokens_out=9),
        make_observation("c", "no", latency=40, tokens_in=1, tokens_out=1),
    ]
    weights = {"a": 1.5, "b": 2.0, "c": 0.5}

    candidate_set = CandidateSet.from_observations(enumerate(observations), weights)
    assert not candidate_set.is_empty()

    values = sorted(candidate_set.values(), key=lambda item: item.text)
    no, yes = values

    assert yes.votes == 2
    assert yes.weight == weights["a"] + weights["b"]
    assert yes.score == 0.0
    assert yes.latency == 80
    assert yes.cost == 12.0
    assert yes.stable_index == 0

    assert no.votes == 1
    assert no.weight == weights["c"]
    assert no.score == 0.0
    assert no.latency == 40
    assert no.cost == 2.0
    assert no.stable_index == 2

    tally = candidate_set.tally()
    assert tally == {"yes": 2, "no": 1}

    pool, pivot, _ = candidate_set.select("majority")
    assert pivot == 2.0
    assert [candidate.text for candidate in pool] == ["yes"]


def test_validate_consensus_schema_returns_failures(make_observation):
    observations = [
        make_observation("a", "{\"answer\": 42}", latency=100),
        make_observation("b", "{\"extra\": true}", latency=90),
        make_observation("c", "invalid", latency=80),
    ]
    schema = '{"type": "object", "required": ["answer"]}'

    valid_entries, failures, validated = validate_consensus_schema(observations, schema)

    assert validated is True
    assert valid_entries == [(0, observations[0])]
    assert failures == {1: "missing keys: answer", 2: "invalid json: Expecting value"}


def test_apply_tie_breaker_aliases(make_observation):
    observations = [
        make_observation("a", "foo", latency=60, cost_estimate=5.0),
        make_observation("b", "bar", latency=50, cost_estimate=10.0),
    ]
    candidates = CandidateSet.from_observations(enumerate(observations), None).values()

    narrowed, reason, normalized = _apply_tie_breaker("min-latency", candidates)
    assert [candidate.text for candidate in narrowed] == ["bar"]
    assert reason == "min_latency(min=50)"
    assert normalized == "min_latency"

    narrowed, reason, normalized = _apply_tie_breaker("min_cost", candidates)
    assert [candidate.text for candidate in narrowed] == ["foo"]
    assert reason == "min_cost(min)"
    assert normalized == "min_cost"
