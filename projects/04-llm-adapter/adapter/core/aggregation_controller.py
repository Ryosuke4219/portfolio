"""集約処理の調停。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING, cast

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


class _CompositeTieBreaker(TieBreaker):
    _DISPLAY_NAMES = {"latency": "latency", "cost": "cost", "stable_order": "first"}

    def __init__(
        self,
        order: Sequence[tuple[str, Callable[[AggregationCandidate], float | int]]],
    ) -> None:
        if not order:
            raise ValueError("tie breaker order must not be empty")
        self._order = list(order)
        self._last_used = self._DISPLAY_NAMES[self._order[-1][0]]

    @property
    def name(self) -> str:
        return self._last_used

    def break_tie(self, candidates: Sequence[AggregationCandidate]) -> AggregationCandidate:
        if not candidates:
            raise ValueError("TieBreaker: candidates must be non-empty")
        scored: list[tuple[tuple[float | int, ...], AggregationCandidate]] = []
        for candidate in candidates:
            score = tuple(key(candidate) for _, key in self._order)
            scored.append((score, candidate))
        scored.sort(key=lambda item: item[0])
        best_score, best_candidate = scored[0]
        chosen_name = self._order[-1][0]
        for index, (name, _) in enumerate(self._order):
            pivot = best_score[index]
            if any(entry[0][index] != pivot for entry in scored[1:]):
                chosen_name = name
                break
        self._last_used = self._DISPLAY_NAMES[chosen_name]
        return best_candidate


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
        self._cached_schema_path: Path | None = None
        self._cached_schema: Mapping[str, Any] | None = None

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
        if mode == "consensus":
            quorum_value = (
                config.quorum
                if config.quorum is not None
                else len(selection.decision.candidates)
            )
            consensus_meta: dict[str, object] = {
                "strategy": selection.decision.strategy,
                "quorum": quorum_value,
                "chosen_provider": selection.decision.chosen.provider,
            }
            if selection.votes is not None:
                consensus_meta["votes"] = selection.votes
            if selection.decision.tie_breaker_used:
                consensus_meta["tie_breaker"] = selection.decision.tie_breaker_used
            if selection.decision.reason:
                consensus_meta["reason"] = selection.decision.reason
            score_map = {
                candidate.provider: candidate.score
                for candidate in selection.decision.candidates
                if candidate.score is not None
            }
            if score_map:
                consensus_meta["scores"] = score_map
            if selection.decision.metadata:
                consensus_meta["metadata"] = selection.decision.metadata
            meta["consensus"] = consensus_meta
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
            quorum = quorum_value if quorum_value is not None else 2
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
        schema_data = self._load_schema(getattr(config, "schema", None))
        return AggregationStrategy.from_string(aggregate, schema=schema_data)

    @staticmethod
    def _resolve_tie_breaker(
        config: RunnerConfig,
        lookup: Mapping[int, SingleRunResult],
    ) -> TieBreaker | None:
        tie_name = (config.tie_breaker or "").strip().lower()
        alias = {
            "latency": "latency",
            "min_latency": "latency",
            "cost": "cost",
            "min_cost": "cost",
            "first": "stable_order",
            "stable_order": "stable_order",
        }
        preferred = alias.get(tie_name) if tie_name else None
        if preferred == "stable_order" and tie_name:
            return FirstTieBreaker()
        if tie_name and preferred is None:
            return None

        key_funcs: dict[str, Callable[[AggregationCandidate], float | int]] = {
            "latency": lambda candidate: lookup[candidate.index].metrics.latency_ms,
            "cost": lambda candidate: lookup[candidate.index].metrics.cost_usd,
            "stable_order": lambda candidate: candidate.index,
        }

        order: list[tuple[str, Callable[[AggregationCandidate], float | int]]] = []
        if preferred is not None:
            order.append((preferred, key_funcs[preferred]))
        for fallback in ("latency", "cost", "stable_order"):
            if all(existing_name != fallback for existing_name, _ in order):
                order.append((fallback, key_funcs[fallback]))
        if not order:
            return None
        if order[0][0] == "stable_order" and len(order) == 1:
            return FirstTieBreaker()
        return _CompositeTieBreaker(order)

    def _load_schema(self, schema_path: Path | None) -> Mapping[str, Any] | None:
        if schema_path is None:
            self._cached_schema_path = None
            self._cached_schema = None
            return None
        if self._cached_schema_path == schema_path and self._cached_schema is not None:
            return self._cached_schema
        if schema_path.exists():
            with schema_path.open("r", encoding="utf-8") as fp:
                self._cached_schema = cast(Mapping[str, Any], json.load(fp))
        else:
            self._cached_schema = None
        self._cached_schema_path = schema_path
        return self._cached_schema

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
            meta = dict(metrics.ci_meta)
            meta["aggregate_mode"] = "consensus"
            meta["aggregate_quorum"] = quorum
            meta["aggregate_votes"] = votes
            metrics.ci_meta = meta
