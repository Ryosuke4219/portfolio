"""集約選択ロジック。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, cast, Protocol, TYPE_CHECKING

from . import aggregation as aggregation_module
from .aggregation import (
    AggregationCandidate,
    AggregationResult,
    AggregationStrategy,
    FirstTieBreaker,
    TieBreaker,
)
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
    votes: float | int | None


class AggregationSelector:
    def __init__(
        self,
        *,
        judge_factory_builder: Callable[[ProviderConfig], JudgeProviderFactory] | None = None,
    ) -> None:
        self._judge_factory_builder = judge_factory_builder
        self._cached_schema_path: Path | None = None
        self._cached_schema: Mapping[str, Any] | None = None

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
        score_metadata: dict[str, float] | None = None
        if strategy.name == "max_score":
            score_metadata = self._score_candidates_with_judge(
                candidates,
                config=config,
                default_judge_config=default_judge_config,
            )
        tiebreaker = self._resolve_tie_breaker(config, lookup)
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

    def _score_candidates_with_judge(
        self,
        candidates: Sequence[AggregationCandidate],
        *,
        config: RunnerConfig,
        default_judge_config: ProviderConfig | None,
    ) -> dict[str, float]:
        judge_config = config.judge_provider or default_judge_config
        if judge_config is None:
            raise ValueError("max_score aggregation requires judge provider configuration")
        if self._judge_factory_builder is None:
            raise ValueError("judge_factory_builder must be provided for max_score aggregation")
        factory = self._judge_factory_builder(judge_config)
        judge = factory.create(model=judge_config.model)
        invoke = getattr(judge, "invoke", None)
        if not callable(invoke):
            raise ValueError("judge instance must expose invoke(request)")
        scores: dict[str, float] = {}
        for candidate in candidates:
            request = {
                "mode": getattr(config, "mode", ""),
                "provider": candidate.provider,
                "index": candidate.index,
                "text": candidate.text if candidate.text is not None else candidate.response.text,
            }
            response = invoke(request)
            score = self._extract_quality_score(response)
            candidate.score = score
            if score is not None:
                scores[candidate.provider] = score
        return scores

    @staticmethod
    def _extract_quality_score(response: object) -> float | None:
        raw = getattr(response, "raw", None)
        if isinstance(raw, Mapping):
            value = raw.get("quality_score")
            if isinstance(value, (int, float)):
                return float(value)
        text = getattr(response, "text", None)
        if isinstance(text, str):
            try:
                return float(text.strip())
            except ValueError:
                return None
        return None

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
        schema_data = self._load_schema(getattr(config, "schema", None))
        provider_weights = getattr(config, "provider_weights", None)
        extra: dict[str, Any] = {"schema": schema_data}
        normalized = aggregate.lower().replace("-", "_") if aggregate else ""
        if normalized in {"weighted_vote", "weighted"}:
            extra["provider_weights"] = provider_weights
        return AggregationStrategy.from_string(aggregate, **extra)

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


__all__ = [
    "AggregationDecision",
    "AggregationSelector",
    "JudgeProviderFactory",
]

