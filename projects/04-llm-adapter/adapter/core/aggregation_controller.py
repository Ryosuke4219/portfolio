"""集約処理の調停。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

from . import aggregation as aggregation_module
from .aggregation import (
    AggregationCandidate,
    AggregationResult,
    AggregationStrategy,
    FirstTieBreaker,
    TieBreaker,
)
from .metrics import hash_text
from .runner_execution import SingleRunResult

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .config import ProviderConfig
    from .runner_api import RunnerConfig

try:  # pragma: no cover - 実環境では src.* が存在する
    from src.llm_adapter.provider_spi import ProviderResponse as JudgeProviderResponse  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
    from dataclasses import dataclass as _dataclass
    from typing import Any as _Any

    @_dataclass(slots=True)
    class JudgeProviderResponse:  # type: ignore[override]
        text: str
        latency_ms: int
        tokens_in: int = 0
        tokens_out: int = 0
        raw: _Any | None = None


class JudgeProviderFactory(Protocol):
    def create(self, *, model: str) -> object:
        ...


class _LatencyTieBreaker(TieBreaker):
    name = "latency"

    def __init__(self, lookup: Mapping[int, SingleRunResult]) -> None:
        self._lookup = lookup

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        return min(
            candidates,
            key=lambda candidate: self._lookup[candidate.index].metrics.latency_ms,
        )


class _CostTieBreaker(TieBreaker):
    name = "cost"

    def __init__(self, lookup: Mapping[int, SingleRunResult]) -> None:
        self._lookup = lookup

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        return min(
            candidates,
            key=lambda candidate: self._lookup[candidate.index].metrics.cost_usd,
        )


@dataclass(slots=True)
class AggregationDecision:
    decision: AggregationResult
    lookup: Mapping[int, SingleRunResult]
    votes: int | None


class AggregationController:
    def __init__(
        self,
        *,
        judge_factory_builder: Callable[[ProviderConfig], JudgeProviderFactory] | None = None,
    ) -> None:
        self._judge_factory_builder = judge_factory_builder

    def apply(
        self,
        *,
        mode: str,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
        default_judge_config: ProviderConfig | None,
    ) -> None:
        selection = self._select_aggregation(
            mode,
            config,
            batch,
            default_judge_config=default_judge_config,
        )
        if selection is None:
            return
        winner = selection.lookup.get(selection.decision.chosen.index)
        if winner is None:
            return
        aggregate_output = (
            selection.decision.chosen.text
            or selection.decision.chosen.response.text
            or ""
        )
        winner.aggregate_output = aggregate_output
        meta = dict(winner.metrics.ci_meta)
        meta["aggregate_mode"] = mode
        meta["aggregate_strategy"] = selection.decision.strategy
        if selection.decision.reason:
            meta["aggregate_reason"] = selection.decision.reason
        if selection.decision.tie_breaker_used:
            meta["aggregate_tie_breaker"] = selection.decision.tie_breaker_used
        if selection.decision.metadata:
            for key, value in selection.decision.metadata.items():
                meta[f"aggregate_{key}"] = value
        meta["aggregate_hash"] = hash_text(aggregate_output)
        if selection.votes is not None:
            meta["aggregate_votes"] = selection.votes
        winner.metrics.ci_meta = meta

    def _select_aggregation(
        self,
        mode: str,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
        *,
        default_judge_config: ProviderConfig | None,
    ) -> AggregationDecision | None:
        if not batch:
            return None
        lookup: dict[int, SingleRunResult] = {index: result for index, result in batch}
        candidates = [
            AggregationCandidate(
                index=index,
                provider=result.metrics.provider,
                response=JudgeProviderResponse(
                    text=result.raw_output,
                    latency_ms=result.metrics.latency_ms,
                    tokens_in=result.metrics.input_tokens,
                    tokens_out=result.metrics.output_tokens,
                ),
                text=result.raw_output,
            )
            for index, result in batch
            if result.metrics.status == "ok" and result.raw_output.strip()
        ]
        if not candidates:
            return None
        strategy = self._resolve_aggregation_strategy(
            mode,
            config,
            default_judge_config=default_judge_config,
        )
        if strategy is None:
            return None
        tiebreaker = self._resolve_tie_breaker(config, lookup)
        decision = strategy.aggregate(candidates, tiebreaker=tiebreaker)
        votes: int | None = None
        if mode == "consensus":
            if decision.metadata:
                raw_votes = decision.metadata.get("bucket_size")
                if isinstance(raw_votes, int):
                    votes = raw_votes
            if votes is None:
                chosen_text = decision.chosen.text or decision.chosen.response.text or ""
                winner_output = chosen_text.strip()
                votes = sum(
                    1
                    for result in lookup.values()
                    if result.metrics.status == "ok"
                    and result.raw_output.strip() == winner_output
                )
            quorum_value = config.quorum
            quorum = quorum_value if quorum_value is not None else len(candidates)
            if votes < quorum:
                self._mark_consensus_failure(lookup.values(), quorum, votes)
                return None
        return AggregationDecision(decision=decision, lookup=lookup, votes=votes)

    def _resolve_aggregation_strategy(
        self,
        mode: str,
        config: RunnerConfig,
        *,
        default_judge_config: ProviderConfig | None,
    ) -> AggregationStrategy | None:
        aggregate_raw = config.aggregate
        aggregate = (aggregate_raw or "").strip()
        if not aggregate:
            aggregate = "majority"
        if aggregate.lower() in {"judge", "llm-judge"}:
            judge_config = config.judge_provider or default_judge_config
            if judge_config is None:
                raise ValueError("aggregate=judge requires judge provider configuration")
            if self._judge_factory_builder is None:
                raise ValueError("judge_factory_builder must be provided for judge aggregation")
            if "JudgeStrategy" not in aggregation_module.__dict__:
                attr_name = "JudgeStrategy"
                aggregation_module.JudgeStrategy = getattr(  # type: ignore[attr-defined]
                    aggregation_module, attr_name
                )
            factory = self._judge_factory_builder(judge_config)
            return AggregationStrategy.from_string(
                aggregate,
                model=judge_config.model,
                provider_factory=factory,
            )
        return AggregationStrategy.from_string(aggregate)

    @staticmethod
    def _resolve_tie_breaker(
        config: RunnerConfig,
        lookup: Mapping[int, SingleRunResult],
    ) -> TieBreaker | None:
        tie_name = (config.tie_breaker or "").strip().lower()
        if not tie_name:
            return None
        if tie_name == "latency":
            return _LatencyTieBreaker(lookup)
        if tie_name == "cost":
            return _CostTieBreaker(lookup)
        if tie_name == "first":
            return FirstTieBreaker()
        return None

    @staticmethod
    def _mark_consensus_failure(
        results: Iterable[SingleRunResult],
        quorum: int,
        votes: int,
    ) -> None:
        message = f"consensus quorum not reached (votes={votes}, quorum={quorum})"
        for result in results:
            metrics = result.metrics
            if metrics.status == "ok":
                metrics.status = "error"
            if not metrics.failure_kind:
                metrics.failure_kind = "consensus_quorum"
            if metrics.error_message:
                if message not in metrics.error_message:
                    metrics.error_message = f"{metrics.error_message} | {message}"
            else:
                metrics.error_message = message
