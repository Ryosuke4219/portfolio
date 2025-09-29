"""応答集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast, Protocol, runtime_checkable

# 依存は実行時読み込み。型は実体を使う（mypy用に直import）
try:  # pragma: no cover - 実環境では src.* が存在する
    from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
    from .providers import ProviderResponse  # type: ignore

    @dataclass(slots=True)
    class ProviderRequest:  # type: ignore[override]
        model: str
        prompt: str = ""
        messages: Sequence[Mapping[str, Any]] | None = None
        max_tokens: int | None = None
        temperature: float | None = None
        top_p: float | None = None
        stop: tuple[str, ...] | None = None
        timeout_s: float | None = None
        metadata: Mapping[str, Any] | None = None
        options: dict[str, Any] = field(default_factory=dict)

        @property
        def prompt_text(self) -> str:
            return self.prompt

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


# --- Judge（LLM判定） ---


class JudgeStrategy:
    """
    LLM ジャッジにより最良を選ぶ。
    - provider_factory.create(model=...) で判定用プロバイダを作成
    - 候補を列挙したプロンプトを与え、選択インデックスを抽出
    """

    name = "judge"

    def __init__(
        self,
        *,
        model: str,
        provider_factory: Any,
        prompt_template: str | None = None,
    ) -> None:
        self._model = model
        self._provider_factory = provider_factory
        self._prompt_template = prompt_template or DEFAULT_JUDGE_TEMPLATE

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("judge: candidates must be non-empty")

        # プロンプト生成（1-basedで番号付け）
        rows: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            raw = candidate.text if candidate.text is not None else candidate.response.text
            text = raw.strip()
            rows.append(f"{index}. {text}")

        prompt = self._prompt_template.format(candidates="\n".join(rows))

        # ジャッジプロバイダを作成して問い合わせ
        judge = self._provider_factory.create(model=self._model)
        request = ProviderRequest(model=self._model, prompt=prompt, max_tokens=16, temperature=0.0)
        response: ProviderResponse = judge.invoke(request)

        index_or_none = _parse_choice_index(response.text, total=len(candidates))
        if index_or_none is None:
            breaker = tiebreaker or FirstTieBreaker()
            chosen = breaker.break_tie(candidates)
            return AggregationResult(
                chosen=chosen,
                candidates=list(candidates),
                strategy=self.name,
                reason="judge parse failed → tie-break",
                tie_breaker_used=breaker.name,
                metadata={"judge_raw": response.text},
            )

        index = index_or_none
        chosen = candidates[index]
        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason=f"judge selected {index + 1}",
            tie_breaker_used=None,
            metadata={"judge_raw": response.text},
        )


DEFAULT_JUDGE_TEMPLATE = (
    """You are a strict evaluator.
Read the following candidates and choose the single best answer.

Candidates:
{candidates}

Rules:
- Output only the number of the chosen candidate on the first line (e.g., \"2\").
- Do not add explanations.

Answer with the number only.
""".strip()
)


def _parse_choice_index(text: str, *, total: int) -> int | None:
    """
    返答から 1..total の整数を抽出して 0-based index を返す。
    先頭行優先、なければ最小の妥当数字を拾う。
    """

    import re

    if not text:
        return None

    first_line = text.strip().splitlines()[0]
    for chunk in (first_line, text):
        match = re.search(r"\b([1-9][0-9]?)\b", chunk)
        if not match:
            continue
        value = int(match.group(1))
        if 1 <= value <= total:
            return value - 1
    return None


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
    "JudgeStrategy",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
]
