"""LLM ジャッジ集約の実装。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any, Callable, Protocol, runtime_checkable

from ..aggregation import (
    AggregationCandidate,
    AggregationResult,
    FirstTieBreaker,
    TieBreaker,
)


class SupportsJudgeResponse(Protocol):
    """最小限のジャッジ応答プロトコル。"""

    text: str


@runtime_checkable
class JudgeProvider(Protocol):
    """JudgeStrategy が利用するプロバイダ。"""

    def invoke(self, request: object) -> SupportsJudgeResponse:
        ...


@runtime_checkable
class JudgeProviderFactory(Protocol):
    """JudgeStrategy が呼び出すファクトリ。"""

    def create(self, *, model: str) -> JudgeProvider:
        ...


RequestFactory = Callable[..., object]


@dataclass(slots=True)
class _FallbackProviderRequest:
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


def _default_request_factory(**kwargs: Any) -> object:
    return _FallbackProviderRequest(**kwargs)


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
        provider_factory: JudgeProviderFactory,
        prompt_template: str | None = None,
        request_factory: RequestFactory | None = None,
    ) -> None:
        self._model = model
        self._provider_factory = provider_factory
        self._prompt_template = prompt_template or DEFAULT_JUDGE_TEMPLATE
        self._request_factory = request_factory or _default_request_factory

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("judge: candidates must be non-empty")

        rows: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            raw = candidate.text if candidate.text is not None else candidate.response.text
            text = raw.strip()
            rows.append(f"{index}. {text}")

        prompt = self._prompt_template.format(candidates="\n".join(rows))

        judge = self._provider_factory.create(model=self._model)
        request = self._request_factory(
            model=self._model,
            prompt=prompt,
            max_tokens=16,
            temperature=0.0,
        )
        response = judge.invoke(request)

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
