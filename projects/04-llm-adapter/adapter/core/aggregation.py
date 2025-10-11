"""応答集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Any, Protocol, runtime_checkable, TYPE_CHECKING

__path__ = [str(Path(__file__).with_name("aggregation"))]

from .providers import ProviderResponse


@dataclass(slots=True)
class AggregationCandidate:
    index: int
    provider: str
    response: ProviderResponse
    text: str | None = None
    score: float | None = None


@dataclass(slots=True)
class AggregationResult:
    chosen: AggregationCandidate
    candidates: list[AggregationCandidate]
    strategy: str
    reason: str | None = None
    tie_breaker_used: str | None = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class TieBreaker(Protocol):
    name: str

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate: ...


@runtime_checkable
class AggregationStrategy(Protocol):
    name: str

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult: ...

    @staticmethod
    def from_string(kind: str, **kwargs: Any) -> AggregationStrategy:
        from .aggregation import strategies_builtin as _strategies_builtin

        return _strategies_builtin.resolve_builtin_strategy(kind, **kwargs)


_strategies_builtin = importlib.import_module("adapter.core.aggregation.strategies_builtin")

FirstTieBreaker = _strategies_builtin.FirstTieBreaker
MaxScoreTieBreaker = _strategies_builtin.MaxScoreTieBreaker
MajorityVoteStrategy = _strategies_builtin.MajorityVoteStrategy
MaxScoreStrategy = _strategies_builtin.MaxScoreStrategy
WeightedVoteStrategy = _strategies_builtin.WeightedVoteStrategy


def AggregationResolver(kind: str, **kwargs: Any) -> AggregationStrategy:
    return AggregationStrategy.from_string(kind, **kwargs)


__all__ = [
    "AggregationCandidate",
    "AggregationResult",
    "TieBreaker",
    "FirstTieBreaker",
    "MaxScoreTieBreaker",
    "AggregationStrategy",
    "AggregationResolver",
    "DEFAULT_JUDGE_TEMPLATE",
    "JudgeStrategy",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
    "WeightedVoteStrategy",
]


if TYPE_CHECKING:  # pragma: no cover
    from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name in {"DEFAULT_JUDGE_TEMPLATE", "JudgeStrategy"}:
        from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy

        return DEFAULT_JUDGE_TEMPLATE if name == "DEFAULT_JUDGE_TEMPLATE" else JudgeStrategy
    if hasattr(_strategies_builtin, name):
        return getattr(_strategies_builtin, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
