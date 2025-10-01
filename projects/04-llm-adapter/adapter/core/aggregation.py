"""応答集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, Protocol, runtime_checkable, TYPE_CHECKING

__path__ = [str(Path(__file__).with_name("aggregation"))]

try:  # pragma: no cover - 実環境では src.* が存在する
    from src.llm_adapter.provider_spi import ProviderResponse
except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
    from .providers import ProviderResponse


@dataclass(slots=True)
class AggregationCandidate:
    """集約対象となる各候補。"""

    index: int
    provider: str
    response: ProviderResponse
    text: str | None = None
    score: float | None = None


@dataclass(slots=True)
class AggregationResult:
    """集約の最終結果。"""

    chosen: AggregationCandidate
    candidates: list[AggregationCandidate]
    strategy: str
    reason: str | None = None
    tie_breaker_used: str | None = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class TieBreaker(Protocol):
    name: str

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        ...


@runtime_checkable
class AggregationStrategy(Protocol):
    name: str

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        ...

    @staticmethod
    def from_string(kind: str, **kwargs: Any) -> AggregationStrategy:
        from .aggregation.strategies_builtin import BUILTIN_STRATEGY_REGISTRY

        strategy = BUILTIN_STRATEGY_REGISTRY.resolve(kind, **kwargs)
        if strategy is not None:
            return cast(AggregationStrategy, strategy)

        normalized = (kind or "").strip().lower()
        if normalized not in {"judge", "llm-judge"}:
            raise ValueError(f"Unknown aggregation strategy: {kind!r}")

        from .aggregation.judge import JudgeStrategy

        if "model" not in kwargs:
            raise ValueError("JudgeStrategy requires `model=`")
        provider_factory = kwargs.get("provider_factory")
        if provider_factory is None:
            raise ValueError("JudgeStrategy requires `provider_factory=`")
        return cast(
            AggregationStrategy,
            JudgeStrategy(
                model=str(kwargs["model"]),
                provider_factory=provider_factory,
                prompt_template=kwargs.get("prompt_template"),
            ),
        )


from .aggregation.strategies_builtin import (  # noqa: E402  再エクスポート用
    BUILTIN_STRATEGY_REGISTRY,
    FirstTieBreaker,
    MajorityVoteStrategy,
    MaxScoreStrategy,
    MaxScoreTieBreaker,
    WeightedVoteStrategy,
)


def AggregationResolver(kind: str, **kwargs: Any) -> AggregationStrategy:
    return AggregationStrategy.from_string(kind, **kwargs)


__all__ = [
    "AggregationCandidate", "AggregationResult", "TieBreaker", "AggregationStrategy",
    "AggregationResolver", "BUILTIN_STRATEGY_REGISTRY", "FirstTieBreaker",
    "MaxScoreTieBreaker", "MajorityVoteStrategy", "MaxScoreStrategy",
    "WeightedVoteStrategy", "DEFAULT_JUDGE_TEMPLATE", "JudgeStrategy",
]




if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy


def __getattr__(name: str) -> Any:  # pragma: no cover - 動的リレーエクスポート
    if name in {"DEFAULT_JUDGE_TEMPLATE", "JudgeStrategy"}:
        from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy

        return DEFAULT_JUDGE_TEMPLATE if name == "DEFAULT_JUDGE_TEMPLATE" else JudgeStrategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
