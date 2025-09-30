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
        if kind_norm in {"majority", "majority_vote", "vote", "maj"}:
            schema = kwargs.get("schema")
            return cast(AggregationStrategy, MajorityVoteStrategy(schema=schema))
        if kind_norm in {"max", "max_score", "score", "top"}:
            return cast(AggregationStrategy, MaxScoreStrategy())
        if kind_norm in {"weighted", "weighted_vote"}:
            try:
                weights = kwargs["weights"]
            except KeyError as exc:
                raise ValueError("WeightedVoteStrategy requires `weights=`") from exc
            schema = kwargs.get("schema")
            return cast(
                AggregationStrategy,
                WeightedVoteStrategy(weights=cast(Mapping[str, float], weights), schema=schema),
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


class WeightedVoteStrategy(MajorityVoteStrategy):
    """重み付き多数決。重み合計最大のバケットを採択。"""

    name = "weighted_vote"

    def __init__(
        self,
        *,
        weights: Mapping[str, float],
        schema: Mapping[str, Any] | None = None,
        default_weight: float = 1.0,
    ) -> None:
        if not weights:
            raise ValueError("weighted_vote: weights must not be empty")
        super().__init__(schema=schema)
        self._weights = {provider: float(value) for provider, value in weights.items()}
        if any(weight < 0 for weight in self._weights.values()):
            raise ValueError("weighted_vote: weight must be >= 0")
        if any(not provider for provider in self._weights):
            raise ValueError("weighted_vote: provider id must be non-empty")
        self._default_weight = float(default_weight)

    def _candidate_weight(self, candidate: AggregationCandidate) -> float:
        return self._weights.get(candidate.provider, self._default_weight)

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("weighted_vote: candidates must be non-empty")
        buckets: dict[str, list[AggregationCandidate]] = {}
        totals: dict[str, float] = {}
        for candidate in candidates:
            key = self._bucket_key(candidate)
            buckets.setdefault(key, []).append(candidate)
            totals[key] = totals.get(key, 0.0) + self._candidate_weight(candidate)
        top_key = max(totals, key=totals.get)
        top_weight = totals[top_key]
        tied_keys = [key for key, value in totals.items() if value == top_weight]
        breaker = tiebreaker or FirstTieBreaker()
        if len(tied_keys) == 1:
            bucket = buckets[top_key]
            chosen = bucket[0] if len(bucket) == 1 else breaker.break_tie(bucket)
            tie_used = None if len(bucket) == 1 else breaker.name
        else:
            pool = [candidate for key in tied_keys for candidate in buckets[key]]
            chosen = breaker.break_tie(pool)
            top_key = self._bucket_key(chosen)
            tie_used = breaker.name
        metadata = {
            "bucket_size": len(buckets[top_key]),
            "bucket_weight": top_weight,
            "bucket_weights": totals,
            "provider_weights": self._weights,
        }
        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason=f"weighted_vote(weight={top_weight})",
            tie_breaker_used=tie_used,
            metadata=metadata,
        )


class MaxScoreStrategy:
    """score 最大値を採用。全件 score=None の場合はタイブレーカー。"""

    name = "max_score"

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("max_score: candidates must be non-empty")

        score_map = {
            candidate.provider: candidate.score
            for candidate in candidates
            if candidate.score is not None
        }
        if score_map:
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
                metadata={"scores": score_map},
            )

        breaker = tiebreaker or FirstTieBreaker()
        chosen = breaker.break_tie(candidates)
        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason="all scores are None → tie-break",
            tie_breaker_used=breaker.name,
            metadata={"scores": score_map} if score_map else None,
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
