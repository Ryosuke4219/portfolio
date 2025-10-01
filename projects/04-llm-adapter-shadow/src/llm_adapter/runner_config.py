"""Configuration objects for runner orchestration behavior."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .shadow import DEFAULT_METRICS_PATH, MetricsPath

if TYPE_CHECKING:
    from .provider_spi import ProviderSPI


class RunnerMode(str, Enum):
    """Execution strategies supported by :class:`Runner`/``AsyncRunner``."""

    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"


@dataclass(frozen=True)
class ConsensusConfig:
    """Configuration for consensus style orchestrations."""

    strategy: str = "majority_vote"
    quorum: int = 2
    tie_breaker: str | None = None
    schema: str | None = None
    judge: str | None = None
    max_rounds: int | None = None
    provider_weights: dict[str, float] | None = None
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limit_sleep_s: float = 0.05
    timeout_next_provider: bool = True
    retryable_next_provider: bool = True


DEFAULT_MAX_CONCURRENCY = 4


@dataclass(frozen=True)
class RunnerConfig:
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    max_attempts: int | None = None
    mode: RunnerMode | str | Enum = RunnerMode.SEQUENTIAL
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    rpm: int | None = None
    consensus: ConsensusConfig | None = None
    shadow_provider: ProviderSPI | None = None
    metrics_path: MetricsPath = DEFAULT_METRICS_PATH

    def __post_init__(self) -> None:
        if isinstance(self.mode, RunnerMode):
            normalized = self.mode
        else:
            mode_value = self.mode.value if isinstance(self.mode, Enum) else self.mode
            normalized = RunnerMode(mode_value)

        object.__setattr__(self, "mode", normalized)

        max_concurrency = self.max_concurrency
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an int")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be a positive integer")
