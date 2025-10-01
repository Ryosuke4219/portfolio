"""集約選択ロジック。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast, TYPE_CHECKING

from . import aggregation as aggregation_module
from .aggregation import AggregationCandidate, AggregationResult, AggregationStrategy
from .aggregation_selector_components import (
    CandidateBuilder,
    JudgeProviderFactory,
    JudgeScorer,
    SchemaCache,
    TieBreakerFactory,
)
from .runner_execution import SingleRunResult

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .config import ProviderConfig
    from .runner_api import RunnerConfig


@dataclass(slots=True)
class AggregationDecision:
    decision: AggregationResult
    lookup: Mapping[int, SingleRunResult]
    votes: float | int | None


class AggregationSelector:
    def __init__(
        self,
        *,
        judge_factory_builder: Callable[[ProviderConfig], JudgeProviderFactory] | None = None,
        candidate_builder: CandidateBuilder | None = None,
        judge_scorer: JudgeScorer | None = None,
        tie_breaker_factory: TieBreakerFactory | None = None,
        schema_cache: SchemaCache | None = None,
    ) -> None:
        self._judge_factory_builder = judge_factory_builder
        self._candidate_builder = candidate_builder or CandidateBuilder()
        self._tie_breaker_factory = tie_breaker_factory or TieBreakerFactory()
        self._schema_cache = schema_cache or SchemaCache()
        self._judge_scorer = judge_scorer or JudgeScorer(judge_factory_builder)

    def select(
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
        candidates = self._candidate_builder.build(batch)
        if not candidates:
            return None
        strategy = self._resolve_aggregation_strategy(
            mode,
            config,
            default_judge_config=default_judge_config,
        )
        if strategy is None:
            return None
        score_metadata: dict[str, float] | None = None
        if strategy.name == "max_score":
            score_metadata = self._judge_scorer.score(
                candidates,
                config=config,
                default_judge_config=default_judge_config,
            )
        tiebreaker = self._tie_breaker_factory.create(config, lookup)
        decision = strategy.aggregate(candidates, tiebreaker=tiebreaker)
        if score_metadata is not None:
            metadata = dict(decision.metadata) if decision.metadata else {}
            metadata["scores"] = score_metadata
            decision.metadata = metadata
        votes: float | int | None = None
        aggregate_kind = (config.aggregate or "").strip().lower().replace("-", "_")
        is_weighted = aggregate_kind in {"weighted_vote", "weighted"}
        if mode == "consensus":
            if decision.metadata:
                key = "bucket_weight" if is_weighted else "bucket_size"
                raw_votes = decision.metadata.get(key)
                if isinstance(raw_votes, (int, float)):
                    votes = float(raw_votes)
            metadata = dict(decision.metadata or {})
            if is_weighted:
                weighted_votes = metadata.get("weighted_votes")
                if not isinstance(weighted_votes, Mapping):
                    weighted_map: dict[str, float] = {}
                    weights = config.provider_weights or {}
                    for result in lookup.values():
                        if result.metrics.status != "ok":
                            continue
                        text = result.raw_output.strip()
                        if not text:
                            continue
                        weight = float(weights.get(result.metrics.provider, 1.0))
                        weighted_map[text] = weighted_map.get(text, 0.0) + weight
                    metadata["weighted_votes"] = weighted_map
                else:
                    metadata["weighted_votes"] = {
                        str(text): float(weight)
                        for text, weight in weighted_votes.items()
                    }
                if votes is None:
                    chosen_text = decision.chosen.text or decision.chosen.response.text or ""
                    winner_output = chosen_text.strip()
                    weighted_map = cast(Mapping[str, float], metadata.get("weighted_votes", {}))
                    votes = weighted_map.get(winner_output)
                decision.metadata = metadata
            else:
                if votes is None:
                    chosen_text = decision.chosen.text or decision.chosen.response.text or ""
                    winner_output = chosen_text.strip()
                    votes = sum(
                        1
                        for result in lookup.values()
                        if result.metrics.status == "ok"
                        and result.raw_output.strip() == winner_output
                    )
            if votes is not None and not is_weighted:
                votes = int(votes)
        return AggregationDecision(decision=decision, lookup=lookup, votes=votes)

    def _resolve_aggregation_strategy(
        self,
        mode: str,
        config: RunnerConfig,
        *,
        default_judge_config: ProviderConfig | None,
    ) -> AggregationStrategy | None:
        del mode
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
        schema_data = self._schema_cache.load(getattr(config, "schema", None))
        provider_weights = getattr(config, "provider_weights", None)
        extra: dict[str, Any] = {"schema": schema_data}
        normalized = aggregate.lower().replace("-", "_") if aggregate else ""
        if normalized in {"weighted_vote", "weighted"}:
            extra["provider_weights"] = provider_weights
        return AggregationStrategy.from_string(aggregate, **extra)


__all__ = [
    "AggregationDecision",
    "AggregationSelector",
    "JudgeProviderFactory",
]

