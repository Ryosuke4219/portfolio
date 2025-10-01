"""組み込み集約ストラテジとタイブレーカー。"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import re
from typing import Any

from ..aggregation import AggregationCandidate, AggregationResult, TieBreaker

__all__ = [
    "FirstTieBreaker",
    "MaxScoreTieBreaker",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
    "WeightedVoteStrategy",
    "StrategyRegistry",
    "BUILTIN_STRATEGY_REGISTRY",
]


class StrategyRegistry:
    """単純なストラテジレジストリ。"""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., Any]] = {}
        self._aliases: dict[str, str] = {}

    def register(self, name: str, factory: Callable[..., Any], *, aliases: Sequence[str] = ()) -> None:
        key = name.strip().lower()
        self._factories[key] = factory
        for alias in (name, *aliases):
            self._aliases[alias.strip().lower()] = key

    def resolve(self, kind: str, **kwargs: Any) -> Any | None:
        normalized = (kind or "").strip().lower()
        key = self._aliases.get(normalized)
        if key is None:
            return None
        return self._factories[key](**kwargs)


class FirstTieBreaker:
    """決定的：先勝（index最小）。"""

    name = "first"

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("TieBreaker: candidates must be non-empty")
        return min(candidates, key=lambda candidate: candidate.index)


class MaxScoreTieBreaker:
    """スコア最大。全員 None の場合は First にフォールバック。"""

    name = "max_score"

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("TieBreaker: candidates must be non-empty")
        if any(candidate.score is not None for candidate in candidates):
            return max(
                candidates,
                key=lambda candidate: (
                    candidate.score is not None,
                    float(candidate.score or float("-inf")),
                    -candidate.index,
                ),
            )
        return FirstTieBreaker().break_tie(candidates)


_WHITESPACE_RE = re.compile(r"\s+")


class MajorityVoteStrategy:
    """テキスト同一性の多数決（正規化+JSON対応）。引き分けはタイブレーカー。"""

    name = "majority"

    def __init__(self, *, schema: Mapping[str, Any] | None = None) -> None:
        self._schema = schema

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

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("majority: candidates must be non-empty")

        buckets: dict[str, list[AggregationCandidate]] = {}
        for candidate in candidates:
            key = self._bucket_key(candidate)
            buckets.setdefault(key, []).append(candidate)

        max_bucket: list[AggregationCandidate] = []
        max_count = -1
        for bucket in buckets.values():
            if len(bucket) > max_count:
                max_bucket = bucket
                max_count = len(bucket)

        breaker = tiebreaker or FirstTieBreaker()
        chosen = max_bucket[0] if len(max_bucket) == 1 else breaker.break_tie(max_bucket)
        reason = f"majority({max_count})"
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
    """score 最大値を採用。全件 score=None の場合はタイブレーカー。"""

    name = "max_score"

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("max_score: candidates must be non-empty")

        if any(candidate.score is not None for candidate in candidates):
            chosen = max(
                candidates,
                key=lambda candidate: (
                    candidate.score is not None,
                    float(candidate.score or float("-inf")),
                    -candidate.index,
                ),
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
    """プロバイダ重み付き多数決。"""

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
            key = self._majority._bucket_key(candidate)  # noqa: SLF001 - 同一モジュール内の利用
            entry = buckets.setdefault(
                key,
                {
                    "candidates": [],
                    "weight": 0.0,
                    "text": (candidate.text if candidate.text is not None else candidate.response.text) or "",
                },
            )
            entry["candidates"].append(candidate)
            entry["weight"] += self._resolve_weight(candidate.provider)

        max_bucket_key = next(iter(buckets))
        max_bucket = buckets[max_bucket_key]
        max_weight = float(max_bucket["weight"])
        for key, bucket in buckets.items():
            weight = float(bucket["weight"])
            if weight > max_weight:
                max_bucket_key = key
                max_bucket = bucket
                max_weight = weight

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


BUILTIN_STRATEGY_REGISTRY = StrategyRegistry()
BUILTIN_STRATEGY_REGISTRY.register(
    "majority",
    lambda *, schema=None: MajorityVoteStrategy(schema=schema),
    aliases=("vote", "maj"),
)
BUILTIN_STRATEGY_REGISTRY.register("max_score", lambda: MaxScoreStrategy(), aliases=("max", "score", "top"))
BUILTIN_STRATEGY_REGISTRY.register(
    "weighted_vote",
    lambda *, schema=None, provider_weights=None: WeightedVoteStrategy(
        weights=provider_weights,
        schema=schema,
    ),
    aliases=("weighted",),
)
