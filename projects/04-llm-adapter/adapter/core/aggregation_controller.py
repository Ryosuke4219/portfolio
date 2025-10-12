"""集約処理の調停。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .aggregation import AggregationStrategy, TieBreaker
from .aggregation_selector import (
    AggregationDecision,
    AggregationSelector,
    JudgeProviderFactory,
)
from .metrics.models import hash_text
from .runner_execution import SingleRunResult

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .config import ProviderConfig
    from .runner_api import RunnerConfig


class AggregationController:
    def __init__(
        self,
        *,
        judge_factory_builder: Callable[[ProviderConfig], JudgeProviderFactory] | None = None,
    ) -> None:
        self._selector = AggregationSelector(
            judge_factory_builder=judge_factory_builder,
        )

    def apply(
        self,
        *,
        mode: str | Enum,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
        default_judge_config: ProviderConfig | None,
    ) -> None:
        resolved_mode = _resolve_mode(mode)
        selection = self._selector.select(
            resolved_mode,
            config,
            batch,
            default_judge_config=default_judge_config,
        )
        if selection is None:
            return
        fallback_kind: str | None = None
        if resolved_mode == "consensus":
            votes = selection.votes if selection.votes is not None else 0
            votes_int = int(votes)
            quorum_setting = config.quorum
            quorum = quorum_setting if quorum_setting is not None else 2
            if votes < quorum:
                fallback_available = config.judge_provider or default_judge_config
                if fallback_available and selection.decision.strategy != "judge":
                    judge_config = replace(config, aggregate="judge")
                    fallback_selection = self._selector.select(
                        resolved_mode,
                        judge_config,
                        batch,
                        default_judge_config=default_judge_config,
                    )
                    if fallback_selection is not None:
                        selection = fallback_selection
                        selection.votes = votes
                        fallback_kind = "judge"
                    else:
                        self._mark_consensus_failure(
                            selection.lookup.values(), quorum, votes_int
                        )
                        return
                else:
                    self._mark_consensus_failure(
                        selection.lookup.values(), quorum, votes_int
                    )
                    return
        winner = selection.lookup.get(selection.decision.chosen.index)
        if winner is None:
            return
        aggregate_output = (
            selection.decision.chosen.text
            or selection.decision.chosen.response.text
            or ""
        )
        if fallback_kind:
            reason = selection.decision.reason
            fallback_reason = f"fallback={fallback_kind}"
            selection.decision.reason = (
                f"{reason} | {fallback_reason}" if reason else fallback_reason
            )
            metadata = dict(selection.decision.metadata or {})
            metadata["fallback"] = fallback_kind
            selection.decision.metadata = metadata
        winner.aggregate_output = aggregate_output
        meta = dict(winner.metrics.ci_meta)
        meta["aggregate_mode"] = resolved_mode
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
        if resolved_mode == "consensus":
            quorum_value = config.quorum if config.quorum is not None else 2
            meta["aggregate_quorum"] = quorum_value
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
            if fallback_kind:
                consensus_meta["fallback"] = fallback_kind
            meta["consensus"] = consensus_meta
        winner.metrics.ci_meta = meta

    def _select_aggregation(
        self,
        mode: str | Enum,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
        *,
        default_judge_config: ProviderConfig | None,
    ) -> AggregationDecision | None:
        resolved_mode = _resolve_mode(mode)
        selection = self._selector.select(
            resolved_mode,
            config,
            batch,
            default_judge_config=default_judge_config,
        )
        if selection is None:
            return None
        if resolved_mode == "consensus":
            votes = selection.votes if selection.votes is not None else 0
            votes_int = int(votes)
            quorum_setting = config.quorum
            quorum = quorum_setting if quorum_setting is not None else 2
            if votes < quorum:
                self._mark_consensus_failure(
                    selection.lookup.values(), quorum, votes_int
                )
                return None
        return selection

    def _resolve_aggregation_strategy(
        self,
        mode: str | Enum,
        config: RunnerConfig,
        *,
        default_judge_config: ProviderConfig | None,
    ) -> AggregationStrategy | None:
        resolved_mode = _resolve_mode(mode)
        return self._selector._resolve_aggregation_strategy(
            resolved_mode,
            config,
            default_judge_config=default_judge_config,
        )

    @staticmethod
    def _resolve_tie_breaker(
        config: RunnerConfig,
        lookup: Mapping[int, SingleRunResult],
    ) -> TieBreaker | None:
        return AggregationSelector._resolve_tie_breaker(config, lookup)

    def _load_schema(self, schema_path: Path | None) -> Mapping[str, Any] | None:
        return self._selector.load_schema(schema_path)

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


def _resolve_mode(mode: str | Enum) -> str:
    if isinstance(mode, Enum):
        return str(mode.value)
    return str(mode)
