"""集約選択ロジック。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import math
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
    votes: int | None


class AggregationSelector:
    def __init__(
        self,
        *,
        judge_factory_builder: Callable[[ProviderConfig], JudgeProviderFactory] | None = None,
    ) -> None:
        self._judge_factory_builder = judge_factory_builder
        self._cached_schema_path: Path | None = None
        self._cached_schema: Mapping[str, Any] | None = None
        self._latest_provider_weights: dict[str, float] | None = None
        self._latest_candidate_providers: set[str] = set()

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
        self._latest_candidate_providers = {candidate.provider for candidate in candidates}
        self._latest_provider_weights = None
        strategy = self._resolve_aggregation_strategy(
            mode,
            config,
            default_judge_config=default_judge_config,
        )
        if strategy is None:
            self._latest_candidate_providers = set()
            return None
        tiebreaker = self._resolve_tie_breaker(config, lookup)
        decision = strategy.aggregate(candidates, tiebreaker=tiebreaker)
        provider_weights = self._latest_provider_weights
        if provider_weights is not None:
            metadata = dict(decision.metadata) if decision.metadata else {}
            metadata["provider_weights"] = dict(provider_weights)
            decision.metadata = metadata
        self._latest_provider_weights = None
        self._latest_candidate_providers = set()
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
        return AggregationDecision(decision=decision, lookup=lookup, votes=votes)

    def _resolve_aggregation_strategy(
        self,
        mode: str,
        config: RunnerConfig,
        *,
        default_judge_config: ProviderConfig | None,
    ) -> AggregationStrategy | None:
        self._latest_provider_weights = None
        del mode
        aggregate_raw = config.aggregate
        aggregate = (aggregate_raw or "").strip()
        if not aggregate:
            aggregate = "majority"
        normalized = aggregate.lower().replace("-", "_")
        if normalized in {"judge", "llm_judge"}:
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
            self._latest_provider_weights = None
            return AggregationStrategy.from_string(
                aggregate,
                model=judge_config.model,
                provider_factory=factory,
            )
        weights: dict[str, float] | None = None
        if normalized in {"weighted", "weighted_vote", "weightedvote"}:
            weights = self._prepare_provider_weights(config, aggregate)
            self._latest_provider_weights = weights
        schema_data = self._load_schema(getattr(config, "schema", None))
        kwargs: dict[str, Any] = {"schema": schema_data}
        if weights is not None:
            kwargs["weights"] = weights
        return AggregationStrategy.from_string(aggregate, **kwargs)

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

    def _prepare_provider_weights(
        self,
        config: RunnerConfig,
        aggregate_name: str,
    ) -> dict[str, float]:
        raw_weights = config.provider_weights
        if raw_weights is None:
            raise ValueError(
                f"aggregate={aggregate_name} requires provider_weights"
            )
        if not raw_weights:
            raise ValueError("provider_weights must not be empty for weighted aggregation")
        normalized: dict[str, float] = {}
        for provider, raw_value in raw_weights.items():
            if not isinstance(provider, str) or not provider.strip():
                raise ValueError("provider_weights keys must be non-empty strings")
            try:
                weight = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"provider_weights[{provider!r}] must be a number"
                ) from exc
            if not math.isfinite(weight):
                raise ValueError(
                    f"provider_weights[{provider!r}] must be a finite number"
                )
            if weight < 0:
                raise ValueError(
                    f"provider_weights[{provider!r}] must be >= 0"
                )
            normalized[provider] = weight
        if self._latest_candidate_providers:
            unknown = [
                name for name in normalized if name not in self._latest_candidate_providers
            ]
            if unknown:
                joined = ", ".join(sorted(unknown))
                raise ValueError(
                    f"provider_weights contains unknown providers: {joined}"
                )
        return normalized

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

