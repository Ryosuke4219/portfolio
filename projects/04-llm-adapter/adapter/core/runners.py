"""比較ランナーの実装。"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import logging
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderResponse as JudgeProviderResponse
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import (  # type: ignore[import-not-found]
            ProviderResponse as JudgeProviderResponse,
        )
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        from dataclasses import dataclass
        from types import SimpleNamespace
        from typing import Any

        @dataclass(slots=True)
        class JudgeProviderResponse:
            text: str
            latency_ms: int
            tokens_in: int = 0
            tokens_out: int = 0
            raw: Any | None = None

            @property
            def token_usage(self) -> SimpleNamespace:
                return SimpleNamespace(
                    prompt=self.tokens_in,
                    completion=self.tokens_out,
                    total=self.tokens_in + self.tokens_out,
                )

from .aggregation_controller import AggregationController
from .budgets import BudgetManager
from .compare_runner_finalizer import TaskFinalizer
from .config import ProviderConfig
from .datasets import GoldenTask
from .errors import AllFailedError
from .metrics import BudgetSnapshot, EvalMetrics, RunMetrics, compute_diff_rate, hash_text, now_ts
from .providers import BaseProvider, ProviderFactory, ProviderResponse
from .runner_execution import (
    _SchemaValidator,
    _TokenBucket,
    run_parallel_any_sync,
    RunnerExecution,
    SingleRunResult,
)

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig

LOGGER = logging.getLogger(__name__)

__all__ = ["CompareRunner", "run_parallel_any_sync"]


class _JudgeInvoker:
    def __init__(self, provider: BaseProvider, config: ProviderConfig) -> None:
        self._provider = provider
        self._config = config

    def invoke(self, request: object) -> JudgeProviderResponse:
        if hasattr(request, "prompt_text"):
            prompt = request.prompt_text or ""
        elif hasattr(request, "prompt"):
            prompt = request.prompt or ""
        else:
            prompt = ""
        response = self._provider.generate(prompt)
        return JudgeProviderResponse(
            text=response.output_text,
            latency_ms=response.latency_ms,
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            raw={"provider": self._config.provider},
        )


class _JudgeProviderFactoryAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def create(self, *, model: str) -> _JudgeInvoker:
        provider_config = replace(self._config, model=model)
        provider = ProviderFactory.create(provider_config)
        return _JudgeInvoker(provider, provider_config)


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
        resolved_metrics_path = (
            runner_config.metrics_path
            if runner_config and runner_config.metrics_path is not None
            else metrics_path
        )
        self.metrics_path = resolved_metrics_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.allow_overrun = allow_overrun
        self.runner_config = runner_config
        self.resolver = resolver  # 予約（現状未使用）

        self._schema_validator: _SchemaValidator | None = None
        self._token_bucket: _TokenBucket | None = None
        self._judge_provider_config: ProviderConfig | None = (
            runner_config.judge_provider if runner_config else None
        )
        self._shadow_provider = runner_config.shadow_provider if runner_config else None
        self._provider_weights = (
            dict(runner_config.provider_weights)
            if runner_config and runner_config.provider_weights is not None
            else None
        )
        self._backoff = runner_config.backoff if runner_config else None
        self._aggregation = AggregationController(
            judge_factory_builder=lambda cfg: _JudgeProviderFactoryAdapter(cfg)
        )
        self._task_finalizer = TaskFinalizer(self.metrics_path)

    def run(self, repeat: int, config: RunnerConfig) -> list[RunMetrics]:
        repeat = max(repeat, 1)

        self.runner_config = config
        if config.metrics_path is not None and config.metrics_path != self.metrics_path:
            self.metrics_path = config.metrics_path
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            self._task_finalizer.update_metrics_path(self.metrics_path)
        self._shadow_provider = config.shadow_provider
        self._provider_weights = (
            dict(config.provider_weights) if config.provider_weights is not None else None
        )
        self._backoff = config.backoff

        rpm = getattr(config, "rpm", None)
        self._token_bucket = _TokenBucket(rpm)

        schema_path = getattr(config, "schema", None)
        self._schema_validator = _SchemaValidator(schema_path)
        if config.judge_provider is not None:
            self._judge_provider_config = config.judge_provider

        execution = RunnerExecution(
            token_bucket=self._token_bucket,
            schema_validator=self._schema_validator,
            evaluate_budget=self._evaluate_budget,
            build_metrics=self._build_metrics,
            normalize_concurrency=self._normalize_concurrency,
            backoff=self._backoff,
            shadow_provider=self._shadow_provider,
            metrics_path=config.metrics_path,
            provider_weights=self._provider_weights,
        )

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
                try:
                    if config.mode == "sequential":
                        batch, stop_reason = execution.run_sequential_attempt(
                            providers, task, attempt, config.mode
                        )
                    else:
                        batch, stop_reason = execution.run_parallel_attempt(
                            providers, task, attempt, config
                        )
                except AllFailedError as exc:
                    batch = getattr(exc, "results", [])
                    stop_reason = getattr(exc, "stop_reason", None)
                    if batch:
                        self._aggregation.apply(
                            mode=config.mode,
                            config=config,
                            batch=batch,
                            default_judge_config=self._judge_provider_config,
                        )
                        for index, result in batch:
                            histories[index].append(result)
                    self._task_finalizer.finalize_task(
                        task, providers, histories, results
                    )
                    raise
                self._aggregation.apply(
                    mode=config.mode,
                    config=config,
                    batch=batch,
                    default_judge_config=self._judge_provider_config,
                )
                for index, result in batch:
                    histories[index].append(result)
                if stop_reason:
                    break
            self._task_finalizer.finalize_task(task, providers, histories, results)
            if stop_reason:
                LOGGER.warning("予算制約により実行を停止します: %s", stop_reason)
                break
        return results


    def _run_provider_call(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        prompt: str,
    ) -> tuple[ProviderResponse, str, str | None, str | None, int]:
        execution = RunnerExecution(
            token_bucket=self._token_bucket,
            schema_validator=self._schema_validator,
            evaluate_budget=self._evaluate_budget,
            build_metrics=self._build_metrics,
            normalize_concurrency=self._normalize_concurrency,
        )
        return execution._run_provider_call(provider_config, provider, prompt)

    @staticmethod
    def _normalize_concurrency(total: int, limit: int | None) -> int:
        if total <= 0:
            return 1
        if limit is None or limit <= 0:
            return total
        return max(1, min(total, limit))

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
