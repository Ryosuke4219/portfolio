"""Data models for parallel consensus runner."""
from __future__ import annotations

from dataclasses import dataclass

from ..provider_spi import ProviderResponse, TokenUsage


@dataclass(slots=True)
class ConsensusObservation:
    provider_id: str
    response: ProviderResponse | None
    latency_ms: int | None = None
    tokens: TokenUsage | None = None
    cost_estimate: float | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class ConsensusResult:
    response: ProviderResponse
    votes: int
    tally: dict[str, int]
    total_voters: int
    reason: str
    strategy: str
    min_votes: int | None
    score_threshold: float | None
    tie_breaker: str | None
    tie_break_applied: bool
    tie_break_reason: str | None
    tie_breaker_selected: str | None
    winner_score: float
    abstained: int
    rounds: int
    schema_checked: bool
    schema_failures: dict[int, str]
    judge_name: str | None
    judge_score: float | None
    scores: dict[str, float] | None


__all__ = ["ConsensusObservation", "ConsensusResult"]
