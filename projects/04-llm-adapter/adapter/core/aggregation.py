"""応答集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, cast, Protocol, runtime_checkable, TYPE_CHECKING

__path__ = [str(Path(__file__).with_name("aggregation"))]

# 依存は実行時読み込み。型は実体を使う（mypy用に直import）
try:  # pragma: no cover - 実環境では src.* が存在する
    from src.llm_adapter.provider_spi import ProviderResponse  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
    from .providers import ProviderResponse  # type: ignore

# ===== 基本データ構造 =====


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


# ===== タイブレーカー抽象 =====


@runtime_checkable
class TieBreaker(Protocol):
    name: str

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        ...


class FirstTieBreaker:
    """決定的：先勝（index最小）"""

    name = "first"

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("TieBreaker: candidates must be non-empty")
        return min(candidates, key=lambda c: c.index)


class MaxScoreTieBreaker:
    """スコア最大。全員 None の場合は First にフォールバック。"""

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


# ===== 集約ストラテジ抽象 =====


@runtime_checkable
class AggregationStrategy(Protocol):
    name: str

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        ...

    @staticmethod
    def from_string(kind: str, **kwargs: Any) -> AggregationStrategy:
        kind_norm = (kind or "").strip().lower()
        if kind_norm in {"majority", "vote", "maj"}:
            schema = kwargs.get("schema")
            return cast(AggregationStrategy, MajorityVoteStrategy(schema=schema))
        if kind_norm in {"max", "score", "top"}:
            return cast(AggregationStrategy, MaxScoreStrategy())
        if kind_norm in {"weighted_vote", "weighted"}:
            schema = kwargs.get("schema")
            provider_weights = kwargs.get("provider_weights")
            return cast(
                AggregationStrategy,
                WeightedVoteStrategy(
                    weights=cast(Mapping[str, float] | None, provider_weights),
                    schema=cast(Mapping[str, Any] | None, schema),
                ),
            )
        if kind_norm in {"judge", "llm-judge"}:
            try:
                model = kwargs["model"]
            except KeyError as e:
                raise ValueError("JudgeStrategy requires `model=`") from e
            provider_factory = kwargs.get("provider_factory")
            if provider_factory is None:
                raise ValueError("JudgeStrategy requires `provider_factory=`")
            prompt_template = kwargs.get("prompt_template")
            return cast(
                AggregationStrategy,
                JudgeStrategy(
                    model=str(model),
                    provider_factory=provider_factory,
                    prompt_template=prompt_template,
                ),
            )
        raise ValueError(f"Unknown aggregation strategy: {kind!r}")


# ===== 既定ストラテジ実装 =====


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


# 便利ヘルパー：API/CLI から簡単に呼べるように
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


if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy


def __getattr__(name: str) -> Any:  # pragma: no cover - 動的リレーエクスポート
    if name in {"DEFAULT_JUDGE_TEMPLATE", "JudgeStrategy"}:
        from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy

        return DEFAULT_JUDGE_TEMPLATE if name == "DEFAULT_JUDGE_TEMPLATE" else JudgeStrategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
