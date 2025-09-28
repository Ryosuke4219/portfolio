"""応答集約ストラテジ。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .loader import load_provider_config
from .models import ProviderConfig
from .providers import ProviderFactory


@dataclass(frozen=True)
class AggregationCandidate:
    """集約対象の候補。"""

    key: str
    content: str
    score: float | None = None


@dataclass(frozen=True)
class AggregationResult:
    """集約処理の結果。"""

    winner: AggregationCandidate
    reason: str | None = None
    raw: Mapping[str, Any] | None = None


class TieBreaker(ABC):
    """同点時のタイブレーク戦略。"""

    name: str = "first"

    @abstractmethod
    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        """同点候補の中から 1 件を選ぶ。"""


class FirstTieBreaker(TieBreaker):
    """最初の候補を採用する単純なタイブレーク。"""

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("tie breaker requires candidates")
        return candidates[0]


class AggregationStrategy(ABC):
    """応答集約戦略の抽象基底。"""

    name: str = ""

    def __init__(self, *, tie_breaker: TieBreaker | None = None) -> None:
        self._tie_breaker = tie_breaker or FirstTieBreaker()

    @abstractmethod
    def aggregate(self, candidates: Sequence[AggregationCandidate]) -> AggregationResult:
        """候補群を集約し単一の結果へ還元する。"""

    @classmethod
    def from_string(cls, value: str, **kwargs: Any) -> AggregationStrategy:
        """文字列指定からストラテジを生成する。"""

        key = value.strip().lower()
        if key in {"majority", "majority-vote"}:
            return MajorityVoteAggregation(**kwargs)
        if key in {"score", "score-max"}:
            return ScoreAggregation(**kwargs)
        if key == "judge":
            judge_cfg = kwargs.pop("judge", None)
            if judge_cfg is None:
                raise ValueError("judge strategy requires provider config")
            return JudgeAggregation(judge=judge_cfg, **kwargs)
        raise ValueError(f"unknown aggregation strategy: {value}")


class MajorityVoteAggregation(AggregationStrategy):
    """単純多数決の集約。"""

    name = "majority"

    def aggregate(self, candidates: Sequence[AggregationCandidate]) -> AggregationResult:
        if not candidates:
            raise ValueError("no candidates to aggregate")
        counts = Counter(candidate.content for candidate in candidates)
        top = max(counts.values())
        winners = [candidate for candidate in candidates if counts[candidate.content] == top]
        if len({candidate.content for candidate in winners}) == 1:
            winner = winners[0]
        else:
            winner = self._tie_breaker.break_tie(winners)
        return AggregationResult(winner=winner, reason="majority", raw={"counts": dict(counts)})


class ScoreAggregation(AggregationStrategy):
    """スコアの最大値を採用する集約。"""

    name = "score"

    def aggregate(self, candidates: Sequence[AggregationCandidate]) -> AggregationResult:
        if not candidates:
            raise ValueError("no candidates to aggregate")
        if any(candidate.score is None for candidate in candidates):
            raise ValueError("score aggregation requires candidate.score")
        top = max(candidate.score for candidate in candidates if candidate.score is not None)
        winners = [candidate for candidate in candidates if candidate.score == top]
        winner = winners[0] if len(winners) == 1 else self._tie_breaker.break_tie(winners)
        return AggregationResult(winner=winner, reason="score", raw={"top_score": top})


class JudgeAggregation(AggregationStrategy):
    """判定用 LLM による集約。"""

    name = "judge"

    def __init__(
        self,
        *,
        judge: ProviderConfig | str | Path,
        tie_breaker: TieBreaker | None = None,
        prompt_template: str | None = None,
    ) -> None:
        super().__init__(tie_breaker=tie_breaker)
        config = judge if isinstance(judge, ProviderConfig) else load_provider_config(Path(judge))
        self._provider = ProviderFactory.create(config)
        self._prompt_template = (
            prompt_template
            or "あなたは複数のモデル出力を審査する判定者です。\n最も適切な応答を選んでください。"
        )

    def aggregate(self, candidates: Sequence[AggregationCandidate]) -> AggregationResult:
        if not candidates:
            raise ValueError("no candidates to aggregate")
        prompt = self._build_prompt(candidates)
        response = self._provider.generate(prompt)
        text = response.output_text.strip()
        winner = self._select_winner(text.splitlines()[0].strip() if text else "", candidates)
        reason = text or None
        if winner is None:
            winner = self._tie_breaker.break_tie(candidates)
            reason = f"tie-break ({reason or 'empty'})"
        return AggregationResult(
            winner=winner,
            reason=reason,
            raw={"prompt": prompt, "response": response.raw_output},
        )

    def _build_prompt(self, candidates: Sequence[AggregationCandidate]) -> str:
        lines = [self._prompt_template.strip(), ""]
        for index, candidate in enumerate(candidates, 1):
            lines.append(f"[{index}] {candidate.key}:\n{candidate.content.strip()}")
        lines.append(
            "\nRespond with the winning index on the first line and optionally a short reason."
        )
        return "\n".join(lines)

    def _select_winner(
        self, first_line: str, candidates: Sequence[AggregationCandidate]
    ) -> AggregationCandidate | None:
        if first_line.isdigit():
            index = int(first_line)
            if 1 <= index <= len(candidates):
                return candidates[index - 1]
        lowered = first_line.lower()
        for index, candidate in enumerate(candidates, 1):
            if lowered == candidate.key.lower() or lowered.startswith(str(index)):
                return candidates[index - 1]
        return None


def AggregationResolver(
    strategy: str,
    *,
    tie_breaker: str | None = None,
    judge: ProviderConfig | str | Path | None = None,
    **kwargs: Any,
) -> AggregationStrategy:
    """集約ストラテジを解決するヘルパー。"""

    name = tie_breaker.strip().lower() if tie_breaker else "first"
    if name != "first":
        raise ValueError(f"unknown tie breaker: {tie_breaker}")
    options = dict(kwargs)
    options["tie_breaker"] = FirstTieBreaker()
    if strategy.strip().lower() == "judge":
        if judge is None:
            raise ValueError("judge strategy requires judge provider")
        options["judge"] = judge
    return AggregationStrategy.from_string(strategy, **options)


__all__ = [
    "AggregationCandidate",
    "AggregationResult",
    "TieBreaker",
    "AggregationStrategy",
    "AggregationResolver",
]
