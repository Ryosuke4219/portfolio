from __future__ import annotations

from collections.abc import Callable
from typing import Mapping

from .majority_vote import MajorityVoteStrategy
from .max_score import MaxScoreStrategy
from .weighted_vote import WeightedVoteStrategy

StrategyFactory = Callable[[], object]

_BUILTINS: Mapping[str, StrategyFactory] = {
    MajorityVoteStrategy.name: MajorityVoteStrategy,
    "majority": MajorityVoteStrategy,
    MaxScoreStrategy.name: MaxScoreStrategy,
    WeightedVoteStrategy.name: WeightedVoteStrategy,
}


def resolve_builtin_strategy(kind: str) -> object:
    try:
        factory = _BUILTINS[kind]
    except KeyError as exc:
        raise ValueError(f"unknown aggregation strategy: {kind}") from exc
    return factory()
