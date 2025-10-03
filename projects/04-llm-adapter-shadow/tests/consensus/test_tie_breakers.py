from collections.abc import Callable

import pytest

from src.llm_adapter.provider_spi import ProviderResponse
from src.llm_adapter.runner_config import ConsensusConfig
from src.llm_adapter.runner_parallel import (
    compute_consensus,
    ConsensusObservation,
    ConsensusResult,
)


def test_majority_with_latency_tie_breaker(
    make_response: Callable[..., ProviderResponse]
) -> None:
    responses = [
        make_response("A", 40),
        make_response("B", 5),
        make_response("A", 35),
        make_response("B", 7),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="majority", tie_breaker="latency", quorum=2),
    )
    assert isinstance(result, ConsensusResult)
    assert result.response.text == "B"
    assert result.votes == 2
    assert result.tie_break_applied is True
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason.startswith("latency")
    tie_breaker_selected = result.tie_breaker_selected
    assert tie_breaker_selected is not None
    assert tie_breaker_selected == "latency"
    assert result.rounds == 2


def test_max_score_strategy_prefers_best_latency(
    make_response: Callable[..., ProviderResponse]
) -> None:
    responses = [
        make_response("A", 18, score=0.6),
        make_response("B", 9, score=0.5),
        make_response("A", 22, score=0.4),
        make_response("B", 7, score=0.6),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="max_score", tie_breaker="latency", quorum=2),
    )
    assert result.response.text == "B"
    assert result.tie_break_applied is True
    tie_breaker_selected = result.tie_breaker_selected
    assert tie_breaker_selected is not None
    assert tie_breaker_selected == "latency"
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason.startswith("latency")
    assert result.scores is not None
    assert result.scores["A"] == pytest.approx(0.6)
    assert result.scores["B"] == pytest.approx(0.6)
    assert result.winner_score == pytest.approx(0.6)


def test_default_tie_break_order(
    make_observation: Callable[..., ConsensusObservation]
) -> None:
    cases = [
        (
            ("alpha", "A", 90, 5.0),
            ("bravo", "B", 35, 1.0),
            "B",
            "min_latency",
            "latency",
        ),
        (
            ("alpha", "A", 40, 4.0),
            ("bravo", "B", 40, 1.5),
            "B",
            "min_cost",
            "cost",
        ),
    ]
    for entry_a, entry_b, expected, tie_breaker, fragment in cases:
        observations = [
            make_observation(*entry, tokens_in=1, tokens_out=1, cost_estimate=entry[3])
            for entry in (entry_a, entry_b)
        ]
        result = compute_consensus(
            observations,
            config=ConsensusConfig(strategy="majority_vote", quorum=1),
        )
        assert result.response.text == expected
        assert result.tie_break_applied is True
        assert result.tie_breaker_selected == tie_breaker
        tie_break_reason = result.tie_break_reason
        assert tie_break_reason is not None
        assert fragment in tie_break_reason


def test_stable_order_makes_tie_resolution_deterministic(
    make_observation: Callable[..., ConsensusObservation]
) -> None:
    observations = [
        make_observation("alpha", "A", 25, tokens_in=1, tokens_out=1, cost_estimate=1.0),
        make_observation("bravo", "B", 25, tokens_in=1, tokens_out=1, cost_estimate=1.0),
    ]
    flipped = list(reversed(observations))
    first = compute_consensus(
        observations,
        config=ConsensusConfig(strategy="majority_vote", quorum=1),
    )
    second = compute_consensus(
        flipped,
        config=ConsensusConfig(strategy="majority_vote", quorum=1),
    )
    assert first.response.text == second.response.text
    assert first.tie_breaker_selected == "stable_order"
    assert second.tie_breaker_selected == "stable_order"
