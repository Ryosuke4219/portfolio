"""応答集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import re
from pathlib import Path
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
    """テキスト/JSON の正規化多数決。引き分けはタイブレーカー。"""

    name = "majority"

    def __init__(self, *, schema: Mapping[str, object] | None = None) -> None:
        self._schema = dict(schema) if schema else None
        self._json_enabled = False
        self._expected_keys: set[str] | None = None
        self._property_types: dict[str, str] = {}
        if isinstance(self._schema, dict):
            schema_type = self._schema.get("type")
            if schema_type == "object":
                self._json_enabled = True
                properties = self._schema.get("properties")
                if isinstance(properties, Mapping):
                    self._expected_keys = {str(name) for name in properties.keys()}
                    for key, prop in properties.items():
                        if isinstance(prop, Mapping):
                            prop_type = prop.get("type")
                            if isinstance(prop_type, str):
                                self._property_types[str(key)] = prop_type
                required = self._schema.get("required")
                if isinstance(required, list) and required and self._expected_keys is not None:
                    self._expected_keys = {str(name) for name in required}

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("majority: candidates must be non-empty")

        buckets: dict[str, list[AggregationCandidate]] = {}
        for candidate in candidates:
            raw_text = candidate.text if candidate.text is not None else candidate.response.text
            key = self._normalize(raw_text)
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

    def _normalize(self, raw: str | None) -> str:
        if self._json_enabled:
            normalized = self._normalize_json(raw or "")
            if normalized is not None:
                return normalized
        return self._normalize_text(raw or "")

    @staticmethod
    def _normalize_text(raw: str) -> str:
        stripped = raw.strip()
        compressed = re.sub(r"\s+", " ", stripped)
        return compressed.lower()

    def _normalize_json(self, raw: str) -> str | None:
        if not raw.strip():
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        if self._expected_keys is not None:
            actual_keys = {str(key) for key in data.keys()}
            if actual_keys != self._expected_keys:
                return None
        for key, expected_type in self._property_types.items():
            if key not in data:
                continue
            if not self._match_type(data[key], expected_type):
                return None
        return json.dumps(
            {str(key): data[key] for key in sorted(data.keys(), key=str)},
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _match_type(value: object, expected_type: str) -> bool:
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "null":
            return value is None
        return True


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


if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy


def __getattr__(name: str) -> Any:  # pragma: no cover - 動的リレーエクスポート
    if name in {"DEFAULT_JUDGE_TEMPLATE", "JudgeStrategy"}:
        from .aggregation.judge import DEFAULT_JUDGE_TEMPLATE, JudgeStrategy

        return DEFAULT_JUDGE_TEMPLATE if name == "DEFAULT_JUDGE_TEMPLATE" else JudgeStrategy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
