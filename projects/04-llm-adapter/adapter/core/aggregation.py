"""応答集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

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
            return cast(AggregationStrategy, MajorityVoteStrategy())
        if kind_norm in {"max", "score", "top"}:
            return cast(AggregationStrategy, MaxScoreStrategy())
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


class MajorityVoteStrategy:
    """テキスト同一性の多数決（完全一致）。引き分けはタイブレーカー。"""

    name = "majority"

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("majority: candidates must be non-empty")

        # 正規化：空(None/空文字)は "" として扱いカウント可能に
        def norm(s: str | None) -> str:
            return (s or "").strip()

        buckets: dict[str, list[AggregationCandidate]] = {}
        for candidate in candidates:
            key = norm(candidate.text if candidate.text is not None else candidate.response.text)
            buckets.setdefault(key, []).append(candidate)

        # 最大票のバケットを抽出
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


from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy


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
]
