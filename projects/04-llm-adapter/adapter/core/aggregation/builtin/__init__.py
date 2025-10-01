"""組み込み集約ストラテジモジュール群。"""
from __future__ import annotations

from .majority_vote import MajorityVoteStrategy
from .max_score import MaxScoreStrategy
from .registry import (
    resolve_builtin_strategy,
    STRATEGY_ALIASES,
    STRATEGY_FACTORIES,
    StrategyFactory,
)
from .tie_breakers import FirstTieBreaker, MaxScoreTieBreaker
from .weighted_vote import WeightedVoteStrategy

__all__ = [
    "FirstTieBreaker",
    "MaxScoreTieBreaker",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
    "WeightedVoteStrategy",
    "StrategyFactory",
    "STRATEGY_FACTORIES",
    "STRATEGY_ALIASES",
    "resolve_builtin_strategy",
]
