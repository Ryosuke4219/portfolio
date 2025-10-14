from collections.abc import Callable

import pytest

from llm_adapter.provider_spi import ProviderResponse
from llm_adapter.runner_config import ConsensusConfig
from llm_adapter.runner_parallel.consensus import (
    compute_consensus,
    ConsensusObservation,
)


def test_weighted_strategy_records_scores(
    make_response: Callable[..., ProviderResponse]
) -> None:
    responses = [
        make_response("A", 10, tokens_in=5, tokens_out=5, score=0.4),
        make_response("A", 12, tokens_in=4, tokens_out=4, score=0.2),
        make_response("B", 9, tokens_in=1, tokens_out=1, score=0.3),
        make_response("B", 8, tokens_in=1, tokens_out=1, score=0.3),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="weighted", tie_breaker="cost", quorum=2),
    )
    assert result.response.text == "B"
    assert result.scores is not None
    assert result.scores["A"] == pytest.approx(0.6)
    assert result.scores["B"] == pytest.approx(0.6)
    assert result.winner_score == pytest.approx(0.6)
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason == "cost(min)"
    tie_breaker_selected = result.tie_breaker_selected
    assert tie_breaker_selected is not None
    assert tie_breaker_selected == "cost"


def test_weighted_vote_uses_provider_weights_and_srs_names(
    make_observation: Callable[..., ConsensusObservation]
) -> None:
    observations = [
        make_observation(provider, text, latency, tokens_in=1, tokens_out=1)
        for provider, text, latency in (
            ("alpha", "A", 80),
            ("bravo", "B", 25),
            ("charlie", "B", 20),
        )
    ]
    result = compute_consensus(
        observations,
        config=ConsensusConfig(
            strategy="weighted_vote",
            tie_breaker="min_latency",
            quorum=1,
            provider_weights={"alpha": 2.0, "bravo": 0.5, "charlie": 0.5},
        ),
    )
    assert result.response.text == "A"
