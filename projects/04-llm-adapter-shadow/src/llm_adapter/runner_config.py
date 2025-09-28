"""Configuration objects for runner orchestration behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RunnerMode(str, Enum):
    """Execution strategies supported by :class:`Runner`/``AsyncRunner``."""

    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"


@dataclass(frozen=True)
class ConsensusConfig:
    """Configuration for consensus style orchestrations."""

    strategy: str = "majority"
    quorum: int | None = None
    tie_breaker: str | None = None
    schema: str | None = None
    judge: str | None = None
    max_rounds: int | None = None


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limit_sleep_s: float = 0.05
    timeout_next_provider: bool = True
    retryable_next_provider: bool = True


@dataclass(frozen=True)
class RunnerConfig:
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    max_attempts: int | None = None
    mode: RunnerMode = RunnerMode.SEQUENTIAL
    max_concurrency: int | None = None
    rpm: int | None = None
    consensus: ConsensusConfig | None = None
