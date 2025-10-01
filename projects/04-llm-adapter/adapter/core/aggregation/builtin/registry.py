"""組み込みストラテジのレジストリ。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping, cast

from .. import AggregationStrategy
from .majority_vote import MajorityVoteStrategy
from .max_score import MaxScoreStrategy
from .weighted_vote import WeightedVoteStrategy

__all__ = [
    "StrategyFactory",
    "resolve_builtin_strategy",
    "STRATEGY_FACTORIES",
    "STRATEGY_ALIASES",
]

StrategyFactory = Callable[..., AggregationStrategy]


def _build_majority(**kwargs: Any) -> AggregationStrategy:
    schema = cast(Mapping[str, Any] | None, kwargs.get("schema"))
    return MajorityVoteStrategy(schema=schema)


def _build_max_score(**_kwargs: Any) -> AggregationStrategy:
    return MaxScoreStrategy()


def _build_weighted(**kwargs: Any) -> AggregationStrategy:
    weights = cast(Mapping[str, float] | None, kwargs.get("provider_weights"))
    schema = cast(Mapping[str, Any] | None, kwargs.get("schema"))
    return WeightedVoteStrategy(weights=weights, schema=schema)


def _build_judge(**kwargs: Any) -> AggregationStrategy:
    from ..judge import JudgeStrategy

    return JudgeStrategy(**kwargs)


STRATEGY_FACTORIES: dict[str, StrategyFactory] = {
    "majority_vote": _build_majority,
    "max_score": _build_max_score,
    "weighted_vote": _build_weighted,
    "judge": _build_judge,
}

STRATEGY_ALIASES: dict[str, set[str]] = {
    "majority_vote": {"majority", "majority_vote", "vote", "maj"},
    "max_score": {"max", "max_score", "score", "top"},
    "weighted_vote": {"weighted_vote", "weighted"},
    "judge": {"judge", "llm_judge"},
}


def resolve_builtin_strategy(kind: str, **kwargs: Any) -> AggregationStrategy:
    kind_norm = (kind or "").strip().lower()
    for key, aliases in STRATEGY_ALIASES.items():
        if kind_norm in aliases:
            factory = STRATEGY_FACTORIES[key]
            return factory(**kwargs)
    raise ValueError(f"Unknown aggregation strategy: {kind!r}")
