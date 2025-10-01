"""組み込み集約ストラテジ群。"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import re
from typing import Any, cast

from ..aggregation import (
    AggregationCandidate,
    AggregationResult,
    AggregationStrategy,
    TieBreaker,
)

__all__ = [
    "FirstTieBreaker",
    "MaxScoreTieBreaker",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
    "WeightedVoteStrategy",
    "resolve_builtin_strategy",
]

_WHITESPACE_RE = re.compile(r"\s+")


class FirstTieBreaker:
    name = "stable_order"

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("TieBreaker: candidates must be non-empty")
        return min(candidates, key=lambda c: c.index)


class MaxScoreTieBreaker:
    name = "max_score"

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("TieBreaker: candidates must be non-empty")
        if any(c.score is not None for c in candidates):
            return max(
                candidates,
                key=lambda c: (c.score is not None, float(c.score or float("-inf")), -c.index),
            )
        return FirstTieBreaker().break_tie(candidates)


class MajorityVoteStrategy:
    name = "majority_vote"

    def __init__(self, *, schema: Mapping[str, Any] | None = None) -> None:
        self._schema = schema
        self._required_keys = self._extract_required_keys(schema)

    def _extract_required_keys(self, schema: Mapping[str, Any] | None) -> frozenset[str]:
        if not isinstance(schema, Mapping):
            return frozenset()
        required = schema.get("required")
        if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
            keys = [key for key in required if isinstance(key, str)]
            return frozenset(keys)
        return frozenset()

    def _normalize_text(self, value: str | None) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return ""
        normalized = _WHITESPACE_RE.sub(" ", normalized)
        return normalized.lower()

    def _json_bucket_key(self, value: str) -> str | None:
        if not self._schema:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return f"json:{canonical}"

    def _bucket_key(self, candidate: AggregationCandidate) -> str:
        raw = candidate.text if candidate.text is not None else candidate.response.text
        json_key = self._json_bucket_key(raw)
        if json_key is not None:
            return json_key
        return self._normalize_text(raw)

    def _bucket_is_complete(self, key: str, candidate: AggregationCandidate) -> bool:
        if not self._required_keys or not key.startswith("json:"):
            return False
        raw = (candidate.text if candidate.text is not None else candidate.response.text) or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        return all(required_key in payload for required_key in self._required_keys)

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("majority_vote: candidates must be non-empty")

        buckets: dict[str, list[AggregationCandidate]] = {}
        completeness: dict[str, bool] = {}
        for candidate in candidates:
            key = self._bucket_key(candidate)
            buckets.setdefault(key, []).append(candidate)
            if key not in completeness:
                completeness[key] = self._bucket_is_complete(key, candidate)

        max_bucket: list[AggregationCandidate] = []
        max_count = -1
        max_complete = False
        for key, bucket in buckets.items():
            count = len(bucket)
            bucket_complete = completeness.get(key, False)
            if count > max_count:
                max_bucket = bucket
                max_count = count
                max_complete = bucket_complete
            elif count == max_count and bucket_complete and not max_complete:
                max_bucket = bucket
                max_complete = True

        breaker = tiebreaker or FirstTieBreaker()
        chosen = max_bucket[0] if len(max_bucket) == 1 else breaker.break_tie(max_bucket)
        reason = f"majority_vote({max_count})"
        tie_used = None if len(max_bucket) == 1 else breaker.name

        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason=reason,
            tie_breaker_used=tie_used,
            metadata={"bucket_size": max_count},
        )


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
                    "text": (candidate.text if candidate.text is not None else candidate.response.text) or "",
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
    from .judge import JudgeStrategy

    return JudgeStrategy(**kwargs)


_STRATEGY_FACTORIES: dict[str, StrategyFactory] = {
    "majority_vote": _build_majority,
    "max_score": _build_max_score,
    "weighted_vote": _build_weighted,
    "judge": _build_judge,
}

_STRATEGY_ALIASES: dict[str, set[str]] = {
    "majority_vote": {"majority", "majority_vote", "vote", "maj"},
    "max_score": {"max", "max_score", "score", "top"},
    "weighted_vote": {"weighted_vote", "weighted"},
    "judge": {"judge", "llm_judge"},
}


def resolve_builtin_strategy(kind: str, **kwargs: Any) -> AggregationStrategy:
    kind_norm = (kind or "").strip().lower()
    for key, aliases in _STRATEGY_ALIASES.items():
        if kind_norm in aliases:
            factory = _STRATEGY_FACTORIES[key]
            return factory(**kwargs)
    raise ValueError(f"Unknown aggregation strategy: {kind!r}")
