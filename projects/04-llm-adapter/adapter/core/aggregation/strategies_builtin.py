"""組み込み集約ストラテジの互換レイヤー。"""
from __future__ import annotations

from .builtin.majority_vote import MajorityVoteStrategy
from .builtin.max_score import MaxScoreStrategy
from .builtin.tie_breakers import FirstTieBreaker, MaxScoreTieBreaker
from .builtin.weighted_vote import WeightedVoteStrategy
from .builtin.registry import resolve_builtin_strategy

__all__ = [
    "FirstTieBreaker",
    "MaxScoreTieBreaker",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
    "WeightedVoteStrategy",
    "resolve_builtin_strategy",
]
