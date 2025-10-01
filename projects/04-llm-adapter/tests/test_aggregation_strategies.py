from adapter.core.aggregation import (
    AggregationCandidate,
    MajorityVoteStrategy,
    MaxScoreStrategy,
    MaxScoreTieBreaker,
    WeightedVoteStrategy,
)
from adapter.core.provider_spi import ProviderResponse


def _candidate(index: int, provider: str, text: str, *, score: float | None = None) -> AggregationCandidate:
    response = ProviderResponse(text=text, latency_ms=0)
    return AggregationCandidate(index=index, provider=provider, response=response, text=text, score=score)


def test_majority_vote_normalizes_buckets() -> None:
    majority = MajorityVoteStrategy()
    cands = [
        _candidate(0, "a", " Hello  WORLD "),
        _candidate(1, "b", "hello world"),
        _candidate(2, "c", "bye"),
    ]
    result = majority.aggregate(cands)
    assert result.chosen == cands[0]
    assert result.strategy == "majority_vote"
    assert result.reason == "majority_vote(2)"
    assert result.metadata == {"bucket_size": 2}


def test_max_score_falls_back_to_tiebreaker() -> None:
    strategy = MaxScoreStrategy()
    cands = [_candidate(0, "a", "x"), _candidate(1, "b", "y")]
    breaker = MaxScoreTieBreaker()
    result = strategy.aggregate(cands, tiebreaker=breaker)
    assert result.chosen == cands[0]
    assert result.tie_breaker_used == breaker.name


def test_weighted_vote_respects_weights_and_tiebreaker() -> None:
    strategy = WeightedVoteStrategy(weights={"a": 2.0, "b": 1.0})
    cands = [
        _candidate(0, "a", "foo", score=0.1),
        _candidate(1, "b", "bar", score=0.9),
        _candidate(2, "b", "foo", score=0.8),
    ]
    breaker = MaxScoreTieBreaker()
    result = strategy.aggregate(cands, tiebreaker=breaker)
    assert result.chosen == cands[2]
    assert result.metadata == {
        "bucket_weight": 3.0,
        "bucket_size": 2,
        "weighted_votes": {"foo": 3.0, "bar": 1.0},
    }
