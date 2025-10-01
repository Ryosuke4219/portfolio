"""Configuration objects for runner orchestration behavior."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, field
from enum import Enum
from typing import Mapping, NamedTuple, TYPE_CHECKING

from .shadow import DEFAULT_METRICS_PATH, MetricsPath

if TYPE_CHECKING:
    from .provider_spi import ProviderSPI


class RunnerMode(str, Enum):
    """Execution strategies supported by :class:`Runner`/``AsyncRunner``."""

    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"


class _FrozenField:
    """Descriptor that exposes a read-only attribute backed by a private slot."""

    def __init__(self, name: str) -> None:
        self._private_name = f"_{name}"
        self._public_name = name

    def __set_name__(self, owner: type[object], name: str) -> None:
        self._private_name = f"_{name}"
        self._public_name = name

    def __get__(self, instance: object | None, owner: type[object]) -> object:
        if instance is None:
            return self
        return getattr(instance, self._private_name)

    def __set__(self, instance: object, value: object) -> None:  # pragma: no cover - defensive
        raise FrozenInstanceError(
            f"Cannot mutate '{self._public_name}' on ConsensusConfig"
        )


@dataclass(eq=True, repr=True, init=False)
class ConsensusConfig:
    """Configuration for consensus style orchestrations."""

    strategy: str = field(default="majority_vote", init=False)
    quorum: int = field(default=2, init=False)
    tie_breaker: str | None = field(default=None, init=False)
    schema: str | None = field(default=None, init=False)
    judge: str | None = field(default=None, init=False)
    max_rounds: int | None = field(default=None, init=False)
    provider_weights: dict[str, float] | None = field(default=None, init=False)
    max_latency_ms: int | None = field(default=None, init=False)
    max_cost_usd: float | None = field(default=None, init=False)

    __slots__ = (
        "_strategy",
        "_quorum",
        "_tie_breaker",
        "_schema",
        "_judge",
        "_max_rounds",
        "_provider_weights",
        "_max_latency_ms",
        "_max_cost_usd",
    )

    strategy = _FrozenField("strategy")
    quorum = _FrozenField("quorum")
    tie_breaker = _FrozenField("tie_breaker")
    schema = _FrozenField("schema")
    judge = _FrozenField("judge")
    max_rounds = _FrozenField("max_rounds")
    provider_weights = _FrozenField("provider_weights")
    max_latency_ms = _FrozenField("max_latency_ms")
    max_cost_usd = _FrozenField("max_cost_usd")

    def __init__(
        self,
        strategy: str = "majority_vote",
        quorum: int = 2,
        tie_breaker: str | None = None,
        schema: str | None = None,
        judge: str | None = None,
        max_rounds: int | None = None,
        provider_weights: dict[str, float] | None = None,
        max_latency_ms: int | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        object.__setattr__(self, "_strategy", strategy)
        object.__setattr__(self, "_quorum", quorum)
        object.__setattr__(self, "_tie_breaker", tie_breaker)
        object.__setattr__(self, "_schema", schema)
        object.__setattr__(self, "_judge", judge)
        object.__setattr__(self, "_max_rounds", max_rounds)
        object.__setattr__(self, "_provider_weights", provider_weights)
        object.__setattr__(self, "_max_latency_ms", max_latency_ms)
        object.__setattr__(self, "_max_cost_usd", max_cost_usd)


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
