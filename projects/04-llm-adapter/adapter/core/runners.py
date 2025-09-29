"""比較ランナーの実装。"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from statistics import median, pstdev
from threading import Lock
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any

from .aggregation import (
    AggregationCandidate,
    AggregationResult,
    AggregationStrategy,
    FirstTieBreaker,
    TieBreaker,
    _resolve_provider_spi,
)
from .budgets import BudgetManager
from .config import ProviderConfig
from .datasets import GoldenTask
from .metrics import (
    BudgetSnapshot,
    EvalMetrics,
    RunMetrics,
    compute_diff_rate,
    estimate_cost,
    hash_text,
    now_ts,
)
from .providers import BaseProvider, ProviderFactory, ProviderResponse

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderResponse as JudgeProviderResponse

    from .runner_api import RunnerConfig
else:  # pragma: no cover - 実行時は遅延解決
    JudgeProviderResponse = Any  # type: ignore[assignment]


def _provider_response_cls() -> type[Any]:
    return _resolve_provider_spi()[1]


@lru_cache(maxsize=1)
def _resolve_runner_parallel() -> tuple[
    type[BaseException], Callable[..., object], Callable[..., object]
]:
    candidates = ("src.llm_adapter.runner_parallel", "llm_adapter.runner_parallel")
    last_error: ModuleNotFoundError | None = None
    for module_name in candidates:
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            last_error = exc
            continue
        return (
            module.ParallelExecutionError,
            module.run_parallel_all_sync,
            module.run_parallel_any_sync,
        )

    message = (
        "Runner parallel module is unavailable. Install `llm-adapter` or ensure "
        "`src.llm_adapter.runner_parallel` can be imported."
    )
    raise ModuleNotFoundError(message) from last_error


def run_parallel_all_sync(workers: Sequence[Callable[[], int]], *, max_concurrency: int) -> None:
    _, run_all, _ = _resolve_runner_parallel()
    run_all(workers, max_concurrency=max_concurrency)


def run_parallel_any_sync(workers: Sequence[Callable[[], int]], *, max_concurrency: int) -> None:
    _, _, run_any = _resolve_runner_parallel()
    run_any(workers, max_concurrency=max_concurrency)


def _parallel_execution_error() -> type[BaseException]:
    error_cls, _, _ = _resolve_runner_parallel()
    return error_cls

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AggregationDecision:
    winner_index: int
    output: str
    votes: int | None = None


@dataclass(slots=True)
class SingleRunResult:
    metrics: RunMetrics
    raw_output: str
    stop_reason: str | None = None
    aggregate_output: str | None = None


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


class _JudgeInvoker:
    def __init__(self, provider: BaseProvider, config: ProviderConfig) -> None:
        self._provider = provider
        self._config = config

    def invoke(self, request: object) -> JudgeProviderResponse:  # type: ignore[override]
        prompt = getattr(request, "prompt_text", "") or getattr(request, "prompt", "")
        response = self._provider.generate(prompt)
        response_cls = _provider_response_cls()
        return response_cls(
            text=response.output_text,
            latency_ms=response.latency_ms,
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            raw={"provider": self._config.provider},
        )


class _JudgeProviderFactoryAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def create(self, *, model: str) -> _JudgeInvoker:  # type: ignore[override]
        provider_config = replace(self._config, model=model)
        provider = ProviderFactory.create(provider_config)
        return _JudgeInvoker(provider, provider_config)


class _TokenBucket:
    def __init__(self, rpm: int | None) -> None:
        self.capacity = rpm or 0
        self.tokens = float(self.capacity)
        self.updated = perf_counter()
        self.lock = Lock()

    def acquire(self) -> None:
        if self.capacity <= 0:
            return
        refill_rate = self.capacity / 60.0
        while True:
            with self.lock:
                now = perf_counter()
                elapsed = now - self.updated
                if elapsed > 0:
                    self.tokens = min(
                        float(self.capacity), self.tokens + elapsed * refill_rate
                    )
                    self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
            sleep(max(1.0 / max(self.capacity, 1), 0.01))


class _SchemaValidator:
    def __init__(self, schema_path: Path | None) -> None:
        self.schema: dict[str, object] | None = None
        if schema_path and schema_path.exists():
            with schema_path.open("r", encoding="utf-8") as fp:
                self.schema = json.load(fp)

    def validate(self, payload: str) -> None:
        if self.schema is None or not payload.strip():
            return
        data = json.loads(payload)
        required = self.schema.get("required") if isinstance(self.schema, dict) else None
        if isinstance(required, list):
            missing = [field for field in required if field not in data]
            if missing:
                raise ValueError(f"missing required fields: {', '.join(missing)}")
        expected_type = self.schema.get("type") if isinstance(self.schema, dict) else None
        if expected_type == "object" and not isinstance(data, dict):
            raise ValueError("schema type mismatch: expected object")


class CompareRunner:
    """プロバイダ横断でゴールデンタスクを評価する。"""

    def __init__(
        self,
        provider_configs: Sequence[ProviderConfig],
        tasks: Sequence[GoldenTask],
        budget_manager: BudgetManager,
        metrics_path: Path,
        allow_overrun: bool = False,
        runner_config: RunnerConfig | None = None,
        resolver: Callable[..., object] | None = None,
    ) -> None:
        self.provider_configs = list(provider_configs)
        self.tasks = list(tasks)
        self.budget_manager = budget_manager
        self.metrics_path = metrics_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.allow_overrun = allow_overrun
        self.runner_config = runner_config
        self.resolver = resolver  # 予約（現状未使用）

        self._schema_validator: _SchemaValidator | None = None
        self._token_bucket: _TokenBucket | None = None
        self._judge_provider_config: ProviderConfig | None = (
            runner_config.judge_provider if runner_config else None
        )

    def run(self, repeat: int, config: RunnerConfig) -> list[RunMetrics]:
        repeat = max(repeat, 1)
        self._token_bucket = _TokenBucket(getattr(config, "rpm", None))
        self._schema_validator = _SchemaValidator(getattr(config, "schema", None))
        self._judge_provider_config = getattr(config, "judge_provider", None)

        providers: list[tuple[ProviderConfig, BaseProvider]] = []
        for provider_config in self.provider_configs:
            provider = ProviderFactory.create(provider_config)
            providers.append((provider_config, provider))
            LOGGER.info(
                "provider=%s model=%s を実行",
                provider_config.provider,
                provider_config.model,
            )

        results: list[RunMetrics] = []
        if not providers:
            return results

        stop_reason: str | None = None
        for task in self.tasks:
            histories: list[list[SingleRunResult]] = [[] for _ in providers]
            for attempt in range(repeat):
                if config.mode == "sequential":
                    batch, stop_reason = self._run_sequential_attempt(
                        providers, task, attempt, config.mode
                    )
                else:
                    batch, stop_reason = self._run_parallel_attempt(
                        providers, task, attempt, config
                    )
                self._apply_aggregation(config.mode, config, batch)
                for index, result in batch:
                    histories[index].append(result)
                if stop_reason:
                    break
            self._finalize_task(task, providers, histories, results)
            if stop_reason:
                LOGGER.warning("予算制約により実行を停止します: %s", stop_reason)
                break
        return results

    def _run_sequential_attempt(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        batch: list[tuple[int, SingleRunResult]] = []
        stop_reason: str | None = None
        for index, (provider_config, provider) in enumerate(providers):
            result = self._run_single(provider_config, provider, task, attempt_index, mode)
            batch.append((index, result))
            if result.stop_reason and not stop_reason:
                stop_reason = result.stop_reason
        return batch, stop_reason

    def _run_parallel_attempt(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        if not providers:
            return [], None
        max_workers = self._normalize_concurrency(
            len(providers), getattr(config, "max_concurrency", None)
        )
        stop_reason: str | None = None
        results: list[SingleRunResult | None] = [None] * len(providers)

        def build_worker(index: int, provider_config: ProviderConfig, provider: BaseProvider):
            def worker() -> int:
                nonlocal stop_reason
                result = self._run_single(
                    provider_config,
                    provider,
                    task,
                    attempt_index,
                    config.mode,
                )
                results[index] = result
                if result.stop_reason and not stop_reason:
                    stop_reason = result.stop_reason
                if (
                    config.mode == "parallel-any"
                    and result.metrics.status != "ok"
                ):
                    raise RuntimeError("parallel-any failure")
                return index

            return worker

        workers = [
            build_worker(index, provider_config, provider)
            for index, (provider_config, provider) in enumerate(providers)
        ]
        if config.mode == "parallel-any":
            try:
                run_parallel_any_sync(workers, max_concurrency=max_workers)
            except (_parallel_execution_error(), RuntimeError):
                pass
        else:
            run_parallel_all_sync(workers, max_concurrency=max_workers)
        batch = [
            (index, result)
            for index, result in enumerate(results)
            if result is not None
        ]
        return batch, stop_reason

    def _apply_aggregation(
        self,
        mode: str,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
    ) -> None:
        selection = self._select_aggregation(mode, config, batch)
        if selection is None:
            return
        decision, result_lookup, votes = selection
        winner = result_lookup.get(decision.chosen.index)
        if winner is None:
            return
        aggregate_output = decision.chosen.text or decision.chosen.response.text or ""
        winner.aggregate_output = aggregate_output
        meta = dict(winner.metrics.ci_meta)
        meta["aggregate_mode"] = mode
        meta["aggregate_strategy"] = decision.strategy
        if decision.reason:
            meta["aggregate_reason"] = decision.reason
        if decision.tie_breaker_used:
            meta["aggregate_tie_breaker"] = decision.tie_breaker_used
        if decision.metadata:
            for key, value in decision.metadata.items():
                meta[f"aggregate_{key}"] = value
        meta["aggregate_hash"] = hash_text(aggregate_output)
        if votes is not None:
            meta["aggregate_votes"] = votes
        winner.metrics.ci_meta = meta

    def _select_aggregation(
        self,
        mode: str,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
    ) -> tuple[AggregationResult, dict[int, SingleRunResult], int | None] | None:
        if not batch:
            return None
        lookup: dict[int, SingleRunResult] = {index: result for index, result in batch}
        candidates = [
            AggregationCandidate(
                index=index,
                provider=result.metrics.provider,
                response=_provider_response_cls()(
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
        strategy = self._resolve_aggregation_strategy(mode, config)
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
            quorum = getattr(config, "quorum", None) or len(candidates)
            if votes < quorum:
                self._mark_consensus_failure(lookup.values(), quorum, votes)
                return None
        return decision, lookup, votes

    def _resolve_aggregation_strategy(
        self, mode: str, config: RunnerConfig
    ) -> AggregationStrategy | None:
        aggregate = (getattr(config, "aggregate", None) or "").strip()
        if not aggregate:
            aggregate = "majority"
        if aggregate.lower() in {"judge", "llm-judge"}:
            judge_config = getattr(config, "judge_provider", None) or self._judge_provider_config
            if judge_config is None:
                raise ValueError("aggregate=judge requires judge provider configuration")
            factory = _JudgeProviderFactoryAdapter(judge_config)
            return AggregationStrategy.from_string(
                aggregate,
                model=judge_config.model,
                provider_factory=factory,
            )
        return AggregationStrategy.from_string(aggregate)

    def _resolve_tie_breaker(
        self,
        config: RunnerConfig,
        lookup: Mapping[int, SingleRunResult],
    ) -> TieBreaker | None:
        name = (getattr(config, "tie_breaker", None) or "").strip().lower()
        if not name:
            return None
        if name == "latency":
            return _LatencyTieBreaker(lookup)
        if name == "cost":
            return _CostTieBreaker(lookup)
        if name == "first":
            return FirstTieBreaker()
        return None

    def _mark_consensus_failure(
        self,
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

    def _finalize_task(
        self,
        task: GoldenTask,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        histories: Sequence[Sequence[SingleRunResult]],
        results: list[RunMetrics],
    ) -> None:
        for index, (provider_config, _) in enumerate(providers):
            attempts = list(histories[index])
            if not attempts:
                continue
            metrics_list = [attempt.metrics for attempt in attempts]
            outputs = [attempt.raw_output for attempt in attempts]
            self._apply_determinism_gate(provider_config, task, metrics_list, outputs)
            for attempt in attempts:
                results.append(attempt.metrics)
                self._append_metric(attempt.metrics)

    @staticmethod
    def _normalize_concurrency(total: int, limit: int | None) -> int:
        if total <= 0:
            return 1
        if limit is None or limit <= 0:
            return total
        return max(1, min(total, limit))

    def _run_single(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> SingleRunResult:
        if self._token_bucket:
            self._token_bucket.acquire()
        prompt = task.render_prompt()
        response, status, failure_kind, error_message, latency_ms = self._run_provider_call(
            provider_config,
            provider,
            prompt,
        )
        cost_usd = estimate_cost(
            provider_config, response.input_tokens, response.output_tokens
        )
        budget_snapshot, stop_reason, status, failure_kind, error_message = (
            self._evaluate_budget(
                provider_config,
                cost_usd,
                status,
                failure_kind,
                error_message,
            )
        )
        schema_error: str | None = None
        validator = self._schema_validator
        if validator is not None:
            try:
                validator.validate(response.output_text or "")
            except ValueError as exc:
                schema_error = str(exc)
        if schema_error:
            if status == "ok":
                status = "error"
            failure_kind = failure_kind or "schema_violation"
            error_message = (
                f"{error_message} | {schema_error}" if error_message else schema_error
            )
        run_metrics, raw_output = self._build_metrics(
            provider_config,
            task,
            attempt_index,
            mode,
            response,
            status,
            failure_kind,
            error_message,
            latency_ms,
            budget_snapshot,
            cost_usd,
        )
        if schema_error:
            run_metrics.status = status
            run_metrics.failure_kind = failure_kind
            run_metrics.error_message = error_message
        return SingleRunResult(
            metrics=run_metrics,
            raw_output=raw_output,
            stop_reason=stop_reason,
        )

    def _run_provider_call(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        prompt: str,
    ) -> tuple[ProviderResponse, str, str | None, str | None, int]:
        response, status, failure_kind, error_message, latency_ms = self._invoke_provider(
            provider, prompt
        )
        status, failure_kind = self._check_timeout(
            provider_config, latency_ms, status, failure_kind
        )
        status, failure_kind = self._enforce_output_guard(
            response.output_text, status, failure_kind
        )
        return response, status, failure_kind, error_message, latency_ms

    def _check_timeout(
        self,
        provider_config: ProviderConfig,
        latency_ms: int,
        status: str,
        failure_kind: str | None,
    ) -> tuple[str, str | None]:
        if (
            provider_config.timeout_s > 0
            and latency_ms > provider_config.timeout_s * 1000
            and status == "ok"
        ):
            return "error", "timeout"
        return status, failure_kind

    def _enforce_output_guard(
        self, output_text: str | None, status: str, failure_kind: str | None
    ) -> tuple[str, str | None]:
        if (output_text is None or not output_text.strip()) and status == "ok":
            return "error", failure_kind or "guard_violation"
        return status, failure_kind

    def _invoke_provider(
        self, provider: BaseProvider, prompt: str
    ) -> tuple[ProviderResponse, str, str | None, str | None, int]:
        start = perf_counter()
        status = "ok"
        failure_kind: str | None = None
        error_message: str | None = None
        try:
            response = provider.generate(prompt)
        except Exception as exc:  # pragma: no cover - 実プロバイダ利用時の防御
            status = "error"
            failure_kind = "provider_error"
            error_message = str(exc)
            latency_ms = int((perf_counter() - start) * 1000)
            # フォールバックのダミー応答
            response = ProviderResponse(
                output_text="",
                input_tokens=len(prompt.split()),
                output_tokens=0,
                latency_ms=latency_ms,
            )
            return response, status, failure_kind, error_message, latency_ms
        return response, status, failure_kind, error_message, response.latency_ms

    def _build_metrics(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        attempt_index: int,
        mode: str,
        response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
        latency_ms: int,
        budget_snapshot: BudgetSnapshot,
        cost_usd: float,
    ) -> tuple[RunMetrics, str]:
        output_text = response.output_text
        eval_metrics, eval_failure_kind = self._evaluate(task, output_text)
        eval_metrics.len_tokens = response.output_tokens
        status, failure_kind = self._merge_eval_failure(
            status, failure_kind, eval_failure_kind
        )
        output_text_record = output_text if provider_config.persist_output else None
        output_hash = self._compute_output_hash(output_text)
        run_metrics = RunMetrics(
            ts=now_ts(),
            run_id=f"run_{task.task_id}_{attempt_index}_{uuid.uuid4().hex}",
            provider=provider_config.provider,
            model=provider_config.model,
            mode=mode,
            prompt_id=task.task_id,
            prompt_name=task.name,
            seed=provider_config.seed,
            temperature=provider_config.temperature,
            top_p=provider_config.top_p,
            max_tokens=provider_config.max_tokens,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            failure_kind=failure_kind,
            error_message=error_message,
            output_text=output_text_record,
            output_hash=output_hash,
            eval=eval_metrics,
            budget=budget_snapshot,
            ci_meta=self._ci_metadata(),
        )
        return run_metrics, output_text or ""

    def _merge_eval_failure(
        self,
        status: str,
        failure_kind: str | None,
        eval_failure_kind: str | None,
    ) -> tuple[str, str | None]:
        if not eval_failure_kind:
            return status, failure_kind
        failure_kind = failure_kind or eval_failure_kind
        if status == "ok":
            status = "error"
        return status, failure_kind

    def _compute_output_hash(self, output_text: str | None) -> str | None:
        return hash_text(output_text) if output_text else None

    def _evaluate_budget(
        self,
        provider_config: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        run_budget_limit = self.budget_manager.run_budget(provider_config.provider)
        run_budget_hit = run_budget_limit > 0 and cost_usd > run_budget_limit
        daily_stop_required = not self.budget_manager.notify_cost(
            provider_config.provider, cost_usd
        )
        budget_snapshot = BudgetSnapshot(
            run_budget_usd=run_budget_limit,
            hit_stop=run_budget_hit or daily_stop_required,
        )
        run_reason: str | None = None
        if run_budget_hit:
            run_reason = (
                f"provider={provider_config.provider} run budget "
                f"{run_budget_limit:.4f} USD exceeded "
                f"(cost={cost_usd:.4f} USD)"
            )
        daily_reason: str | None = None
        if daily_stop_required:
            spent = self.budget_manager.spent_today(provider_config.provider)
            daily_limit = self.budget_manager.daily_budget(provider_config.provider)
            daily_reason = (
                f"provider={provider_config.provider} daily budget "
                f"{daily_limit:.4f} USD exceeded "
                f"(spent={spent:.4f} USD)"
            )
        stop_reason: str | None = None
        if not self.allow_overrun:
            if daily_reason:
                stop_reason = daily_reason
            elif self.budget_manager.should_stop_run(provider_config.provider, cost_usd):
                stop_reason = run_reason
        budget_messages = [msg for msg in (run_reason, daily_reason) if msg]
        if budget_messages:
            if status == "ok":
                status = "error"
            if failure_kind is None:
                failure_kind = "guard_violation"
            joined = " | ".join(budget_messages)
            if error_message:
                error_message = f"{error_message} | {joined}"
            else:
                error_message = joined
            if self.allow_overrun and stop_reason is None:
                LOGGER.warning("予算超過を許容 (--allow-overrun): %s", joined)
        return budget_snapshot, stop_reason, status, failure_kind, error_message

    def _append_metric(self, metrics: RunMetrics) -> None:
        with self.metrics_path.open("a", encoding="utf-8") as fp:
            json.dump(metrics.to_json_dict(), fp, ensure_ascii=False)
            fp.write("\n")

    def _evaluate(
        self, task: GoldenTask, output_text: str | None
    ) -> tuple[EvalMetrics, str | None]:
        expected_type = str(task.expected.get("type", "regex"))
        expected_value = task.expected.get("value")
        eval_metrics = EvalMetrics()
        failure_kind: str | None = None
        if output_text is None:
            return eval_metrics, failure_kind
        if expected_type == "regex" and isinstance(expected_value, str):
            match = re.search(expected_value, output_text)
            eval_metrics.exact_match = bool(match)
            eval_metrics.diff_rate = 0.0 if match else 1.0
        elif expected_type == "literal" and isinstance(expected_value, str):
            eval_metrics.exact_match = output_text.strip() == expected_value.strip()
            eval_metrics.diff_rate = 0.0 if eval_metrics.exact_match else compute_diff_rate(
                output_text, expected_value
            )
        elif expected_type == "json_equal" and expected_value is not None:
            try:
                import json as _json

                actual = _json.loads(output_text)
                eval_metrics.exact_match = actual == expected_value
                eval_metrics.diff_rate = 0.0 if eval_metrics.exact_match else 1.0
            except Exception:
                eval_metrics.exact_match = False
                eval_metrics.diff_rate = 1.0
                failure_kind = "parsing"
        else:
            eval_metrics.diff_rate = 1.0
        return eval_metrics, failure_kind

    def _ci_metadata(self) -> Mapping[str, str]:
        meta: dict[str, str] = {}
        branch = os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_HEAD_REF")
        commit = os.getenv("GITHUB_SHA")
        if branch:
            meta["branch"] = branch
        if commit:
            meta["commit"] = commit
        return meta

    def _apply_determinism_gate(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        metrics_list: Sequence[RunMetrics],
        outputs: Sequence[str],
    ) -> None:
        gates = provider_config.quality_gates
        if gates.determinism_diff_rate_max <= 0 and gates.determinism_len_stdev_max <= 0:
            return
        comparable: list[tuple[RunMetrics, str]] = [
            (metrics, output)
            for metrics, output in zip(metrics_list, outputs, strict=False)
            if metrics.status == "ok" and output
        ]
        if len(comparable) < 2:
            return
        diff_rates: list[float] = []
        for idx, (_, output_a) in enumerate(comparable):
            for _, output_b in comparable[idx + 1 :]:
                diff_rates.append(compute_diff_rate(output_a, output_b))
        median_diff = median(diff_rates) if diff_rates else 0.0
        lengths: list[int] = [
            metrics.eval.len_tokens
            if metrics.eval.len_tokens is not None
            else metrics.output_tokens
            for metrics, _ in comparable
        ]
        len_stdev = pstdev(lengths) if len(lengths) > 1 else 0.0
        diff_threshold_exceeded = (
            gates.determinism_diff_rate_max > 0
            and median_diff > gates.determinism_diff_rate_max
        )
        len_threshold_exceeded = (
            gates.determinism_len_stdev_max > 0
            and len_stdev > gates.determinism_len_stdev_max
        )
        if not (diff_threshold_exceeded or len_threshold_exceeded):
            return
        LOGGER.warning(
            "決定性ゲート失敗: provider=%s model=%s prompt=%s median_diff=%.4f len_stdev=%.4f",
            provider_config.provider,
            provider_config.model,
            task.task_id,
            median_diff,
            len_stdev,
        )
        for metrics, _ in comparable:
            metrics.status = "error"
            metrics.failure_kind = "non_deterministic"
