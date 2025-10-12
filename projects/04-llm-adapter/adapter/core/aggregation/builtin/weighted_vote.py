"""重み付き投票ストラテジ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TYPE_CHECKING

from .. import AggregationCandidate, AggregationResult, TieBreaker
from .majority_vote import MajorityVoteStrategy
from .tie_breakers import FirstTieBreaker

__all__ = ["WeightedVoteStrategy"]


if TYPE_CHECKING:
    from .. import AggregationStrategy


class WeightedVoteStrategy:
    name = "weighted_vote"

    def __init__(
        self,
        *,
        weights: Mapping[str, float] | None = None,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        self._weights = dict(weights or {})
        self._majority = MajorityVoteStrategy(schema=schema)

    def _resolve_weight(self, provider: str) -> float:
        weight = self._weights.get(provider)
        if weight is None:
            return 1.0
        return float(weight)

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("weighted_vote: candidates must be non-empty")

        buckets: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            key = self._majority._bucket_key(candidate)  # noqa: SLF001
            if key not in buckets:
                buckets[key] = {
                    "candidates": [],
                    "weight": 0.0,
                    "text": (candidate.text if candidate.text is not None else candidate.response.text)
                    or "",
                    "complete": self._majority._bucket_is_complete(key, candidate),  # noqa: SLF001
                }
            entry = buckets[key]
            entry["candidates"].append(candidate)
            entry["weight"] += self._resolve_weight(candidate.provider)

        max_bucket_key = next(iter(buckets))
        max_bucket = buckets[max_bucket_key]
        max_weight = float(max_bucket["weight"])
        max_complete = bool(max_bucket.get("complete"))
        for key, bucket in buckets.items():
            weight = float(bucket["weight"])
            complete = bool(bucket.get("complete"))
            if weight > max_weight or (weight == max_weight and complete and not max_complete):
                max_bucket_key = key
                max_bucket = bucket
                max_weight = weight
                max_complete = complete

        bucket_candidates: Sequence[AggregationCandidate] = max_bucket["candidates"]
        breaker = tiebreaker or FirstTieBreaker()
        chosen = (
            bucket_candidates[0]
            if len(bucket_candidates) == 1
            else breaker.break_tie(bucket_candidates)
        )

        metadata = {
            "bucket_weight": max_weight,
            "bucket_size": len(bucket_candidates),
            "weighted_votes": {
                bucket["text"]: float(bucket["weight"])
                for bucket in buckets.values()
            },
        }

        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason=f"weighted({max_weight})",
            tie_breaker_used=None if len(bucket_candidates) == 1 else breaker.name,
            metadata=metadata,
        )

    @staticmethod
    def from_string(kind: str, **kwargs: Any) -> "AggregationStrategy":
        from .registry import resolve_builtin_strategy

        return resolve_builtin_strategy(kind, **kwargs)
