from adapter.core.aggregation import (
    AggregationCandidate,
    MajorityVoteStrategy,
    MaxScoreStrategy,
    MaxScoreTieBreaker,
    WeightedVoteStrategy,
)
from adapter.core.providers import ProviderResponse


def _candidate(idx: int, provider: str, text: str, score: float | None = None) -> AggregationCandidate:
    response = ProviderResponse(text=text)
    return AggregationCandidate(index=idx, provider=provider, response=response, text=text, score=score)


def test_majority_vote_normalizes_text() -> None:
    strategy = MajorityVoteStrategy()
    candidates = [
        _candidate(0, "p1", " Hello  World "),
        _candidate(1, "p2", "hello world"),
        _candidate(2, "p3", "other"),
    ]
    result = strategy.aggregate(candidates)
    assert result.chosen.index == 0
    assert result.metadata == {"bucket_size": 2}


def test_max_score_falls_back_to_tiebreaker() -> None:
    strategy = MaxScoreStrategy()
    candidates = [_candidate(0, "p1", "a"), _candidate(1, "p2", "b")]
    breaker = MaxScoreTieBreaker()
    result = strategy.aggregate(candidates, tiebreaker=breaker)
    assert result.chosen.index == 0
    assert result.tie_breaker_used == breaker.name


def test_weighted_vote_respects_weights_and_tiebreaker() -> None:
    strategy = WeightedVoteStrategy(weights={"p1": 1, "p2": 2, "p3": 2})
    breaker = MaxScoreTieBreaker()
    candidates = [
        _candidate(0, "p1", "same", score=0.1),
        _candidate(1, "p2", "same", score=0.9),
        _candidate(2, "p3", "other", score=0.5),
    ]
    result = strategy.aggregate(candidates, tiebreaker=breaker)
    assert result.chosen.index == 1
    assert result.tie_breaker_used == breaker.name
    assert result.metadata == {
        "bucket_weight": 3.0,
        "bucket_size": 2,
        "weighted_votes": {"same": 3.0, "other": 2.0},
    }
