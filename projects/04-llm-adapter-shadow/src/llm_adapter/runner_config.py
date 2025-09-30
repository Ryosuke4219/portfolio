"""Configuration objects for runner orchestration behavior."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from .provider_spi import ProviderSPI


class ConsensusStrategy(str, Enum):
    MAJORITY_VOTE = "majority_vote"
    WEIGHTED_VOTE = "weighted_vote"
    MAX_SCORE = "max_score"


class ConsensusTieBreaker(str, Enum):
    MIN_LATENCY = "min_latency"
    MIN_COST = "min_cost"
    STABLE_ORDER = "stable_order"


class RunnerMode(str, Enum):
    """Execution strategies supported by :class:`Runner`/``AsyncRunner``."""

    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"


def _normalize_strategy(value: ConsensusStrategy | str) -> ConsensusStrategy:
    if isinstance(value, ConsensusStrategy):
        return value
    normalized = value.strip().lower()
    alias = {
        "majority": ConsensusStrategy.MAJORITY_VOTE,
        "weighted": ConsensusStrategy.WEIGHTED_VOTE,
    }
    try:
        return ConsensusStrategy(normalized)
    except ValueError as exc:  # pragma: no cover - config error
        mapped = alias.get(normalized)
        if mapped is None:
            raise ValueError(f"unsupported consensus strategy: {value!r}") from exc
        return mapped


def _normalize_tie_breaker(
    value: ConsensusTieBreaker | str,
) -> ConsensusTieBreaker:
    if isinstance(value, ConsensusTieBreaker):
        return value
    normalized = value.strip().lower()
    alias = {
        "latency": ConsensusTieBreaker.MIN_LATENCY,
        "cost": ConsensusTieBreaker.MIN_COST,
    }
    try:
        return ConsensusTieBreaker(normalized)
    except ValueError as exc:  # pragma: no cover - config error
        mapped = alias.get(normalized)
        if mapped is None:
            raise ValueError(f"unsupported tie_breaker: {value!r}") from exc
        return mapped


@dataclass(frozen=True)
class ConsensusConfig:
    """Configuration for consensus style orchestrations."""

    strategy: ConsensusStrategy | str = ConsensusStrategy.MAJORITY_VOTE
    quorum: int | None = 2
    tie_breaker: ConsensusTieBreaker | str | None = None
    schema: str | None = None
    judge: str | None = None
    max_rounds: int | None = None
    provider_weights: dict[str, float] | None = None
    shadow_provider: ProviderSPI | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy", _normalize_strategy(self.strategy))
        tie_breaker = self.tie_breaker
        if tie_breaker is not None:
            object.__setattr__(self, "tie_breaker", _normalize_tie_breaker(tie_breaker))
        if self.quorum is not None and self.quorum < 1:
            raise ValueError("quorum must be >= 1")


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limit_sleep_s: float = 0.05
    timeout_next_provider: bool = True
    retryable_next_provider: bool = True


@dataclass(frozen=True)
class RunnerConfig:
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    max_attempts: int | None = None
    mode: RunnerMode | str | Enum = RunnerMode.SEQUENTIAL
    max_concurrency: int | None = None
    rpm: int | None = None
    consensus: ConsensusConfig | None = None
    shadow_provider: ProviderSPI | None = None

    def __post_init__(self) -> None:
        if isinstance(self.mode, RunnerMode):
            normalized = self.mode
        else:
            mode_value = self.mode.value if isinstance(self.mode, Enum) else self.mode
            normalized = RunnerMode(mode_value)

        object.__setattr__(self, "mode", normalized)
