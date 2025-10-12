"""比較ランナーの実装。"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
import logging
from pathlib import Path
from typing import cast, TYPE_CHECKING

from . import errors as core_errors
from .aggregation_controller import AggregationController
from .budgets import BudgetManager
from .compare_runner_finalizer import TaskFinalizer
from .compare_runner_support import (
    _JudgeProviderFactoryAdapter,
    BudgetEvaluator,
    RunMetricsBuilder,
)
from .config import ProviderConfig
from .datasets import GoldenTask
from .execution.compare_task_runner import run_tasks
from .metrics.models import BudgetSnapshot, RunMetrics
from .providers import BaseProvider, ProviderResponse
from .runner_execution import (
    _SchemaValidator,
    _TokenBucket,
    ParallelExecutionError as ExecutionParallelExecutionError,
    run_parallel_any_sync,
    RunnerExecution,
    SingleRunResult,
)

if hasattr(core_errors, "ParallelExecutionError"):
    ParallelExecutionError = cast(
        type[Exception],
        core_errors.ParallelExecutionError,
    )
else:
    ParallelExecutionError = ExecutionParallelExecutionError
    setattr(core_errors, "ParallelExecutionError", ParallelExecutionError)

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig

LOGGER = logging.getLogger(__name__)

__all__ = ["CompareRunner", "run_parallel_any_sync"]


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
        self._metrics_builder = RunMetricsBuilder()
        self._budget_evaluator = BudgetEvaluator(
            budget_manager=self.budget_manager,
            allow_overrun=self.allow_overrun,
            logger=LOGGER,
        )

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

        self._budget_evaluator.allow_overrun = self.allow_overrun
        execution = RunnerExecution(
            token_bucket=self._token_bucket,
            schema_validator=self._schema_validator,
            evaluate_budget=self._budget_evaluator.evaluate,
            build_metrics=self._metrics_builder.build,
            normalize_concurrency=self._normalize_concurrency,
            backoff=self._backoff,
            shadow_provider=self._shadow_provider,
            metrics_path=config.metrics_path,
            provider_weights=self._provider_weights,
        )
        return run_tasks(
            provider_configs=self.provider_configs,
            tasks=self.tasks,
            repeat=repeat,
            config=config,
            execution=execution,
            aggregation_apply=self._apply_aggregation,
            finalize_task=self._task_finalizer.finalize_task,
            judge_provider_config=self._judge_provider_config,
            record_failed_batch=self._record_failed_batch,
            log_attempt_failures=self._log_attempt_failures_with_mode,
            parallel_execution_error=ParallelExecutionError,
        )

    def _record_failed_batch(
        self,
        batch: Sequence[tuple[int, SingleRunResult]],
        config: RunnerConfig,
        histories: list[list[SingleRunResult]],
    ) -> None:
        self._apply_aggregation(
            mode=config.mode,
            config=config,
            batch=batch,
            default_judge_config=self._judge_provider_config,
        )
        for index, result in batch:
            histories[index].append(result)

    def _log_attempt_failures_with_mode(
        self, mode: object, failures: Sequence[object]
    ) -> None:
        self._log_attempt_failures(self._mode_value(mode), failures)

    def _log_attempt_failures(self, mode: str, failures: Sequence[object]) -> None:
        if not failures:
            return
        for record in failures:
            provider = getattr(record, "provider", None)
            status = getattr(record, "status", None)
            failure_kind = getattr(record, "failure_kind", None)
            error_message = getattr(record, "error_message", None)
            LOGGER.warning(
                "モード%s: provider=%s status=%s failure=%s message=%s",
                mode,
                provider,
                status,
                failure_kind,
                error_message,
            )

    def _run_provider_call(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        prompt: str,
    ) -> tuple[ProviderResponse, str, str | None, str | None, int]:
        execution = RunnerExecution(
            token_bucket=self._token_bucket,
            schema_validator=self._schema_validator,
            evaluate_budget=self._budget_evaluator.evaluate,
            build_metrics=self._metrics_builder.build,
            normalize_concurrency=self._normalize_concurrency,
            backoff=self._backoff,
            shadow_provider=self._shadow_provider,
            metrics_path=self.metrics_path,
            provider_weights=self._provider_weights,
        )
        result = execution._run_provider_call(provider_config, provider, prompt)
        return (
            result.response,
            result.status,
            result.failure_kind,
            result.error_message,
            result.latency_ms,
        )

    def _evaluate_budget(
        self,
        provider_config: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        return self._budget_evaluator.evaluate(
            provider_config,
            cost_usd,
            status,
            failure_kind,
            error_message,
        )

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
        return self._metrics_builder.build(
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

    @staticmethod
    def _normalize_concurrency(total: int, limit: int | None) -> int:
        if total <= 0:
            return 1
        if limit is None or limit <= 0:
            return total
        return max(1, min(total, limit))

    @staticmethod
    def _mode_value(mode: object) -> str:
        if isinstance(mode, Enum):
            return str(mode.value)
        return str(mode)

    def _apply_aggregation(
        self,
        *,
        mode: object,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
        default_judge_config: ProviderConfig | None,
    ) -> None:
        normalized = self._mode_value(mode)
        self._aggregation.apply(
            mode=normalized,
            config=config,
            batch=batch,
            default_judge_config=default_judge_config,
        )

