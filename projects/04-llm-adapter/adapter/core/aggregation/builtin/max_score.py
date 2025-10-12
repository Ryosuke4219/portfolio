"""最高スコア選択ストラテジ。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TYPE_CHECKING

from .. import AggregationCandidate, AggregationResult, TieBreaker
from .tie_breakers import FirstTieBreaker

__all__ = ["MaxScoreStrategy"]


if TYPE_CHECKING:
    from .. import AggregationStrategy


class MaxScoreStrategy:
    name = "max_score"

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("max_score: candidates must be non-empty")

        if any(candidate.score is not None for candidate in candidates):
            chosen = max(
                candidates,
                key=lambda c: (c.score is not None, float(c.score or float("-inf")), -c.index),
            )
            return AggregationResult(
                chosen=chosen,
                candidates=list(candidates),
                strategy=self.name,
                reason=f"score={chosen.score}",
                tie_breaker_used=None,
                metadata=None,
            )

        breaker = tiebreaker or FirstTieBreaker()
        chosen = breaker.break_tie(candidates)
        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason="all scores are None → tie-break",
            tie_breaker_used=breaker.name,
            metadata=None,
        )

    @staticmethod
    def from_string(kind: str, **kwargs: Any) -> AggregationStrategy:
        from .registry import resolve_builtin_strategy

        return resolve_builtin_strategy(kind, **kwargs)
