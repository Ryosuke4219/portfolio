"""CompareRunner の実行責務と実行戦略を提供するユーティリティ。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ._parallel_shim import (
    ParallelExecutionError,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from ._provider_execution import _ProviderCallResult, ProviderCallExecutor
from .config import ProviderConfig
from .datasets import GoldenTask
from .execution.guards import _SchemaValidator, _TokenBucket
from .metrics.models import BudgetSnapshot, RunMetrics
from .provider_spi import ProviderSPI
from .providers import BaseProvider, ProviderResponse
from .runner_execution_attempts import (
    ParallelAttemptExecutor,
    SequentialAttemptExecutor,
)
from .runner_execution_call import (
    ensure_invoke_compat,
    execute_provider_with_retries,
    sleep as _retry_sleep,
)
from .runner_execution_metrics import (
    build_single_run_result,
    SingleRunResult,
)
from .runner_execution_shadow import close_shadow_session, open_shadow_session

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import BackoffPolicy, RunnerConfig

_EvaluateBudget = Callable[
    [ProviderConfig, float, str, str | None, str | None],
    tuple[BudgetSnapshot, str | None, str, str | None, str | None],
]
_BuildMetrics = Callable[
    [
        ProviderConfig,
        GoldenTask,
        int,
        str,
        ProviderResponse,
        str,
        str | None,
        str | None,
        int,
        BudgetSnapshot,
        float,
    ],
    tuple[RunMetrics, str],
]
_NormalizeConcurrency = Callable[[int, int | None], int]


class RunnerExecution:
    def __init__(
        self,
        *,
        token_bucket: _TokenBucket | None,
        schema_validator: _SchemaValidator | None,
        evaluate_budget: _EvaluateBudget,
        build_metrics: _BuildMetrics,
        normalize_concurrency: _NormalizeConcurrency,
        backoff: BackoffPolicy | None,
        shadow_provider: ProviderSPI | None,
        metrics_path: Path | None,
        provider_weights: dict[str, float] | None,
    ) -> None:
        self._token_bucket = token_bucket
        self._schema_validator = schema_validator
        self._evaluate_budget = evaluate_budget
        self._build_metrics = build_metrics
        self._normalize_concurrency = normalize_concurrency
        self._backoff = backoff
        self._shadow_provider = shadow_provider
        self._metrics_path = metrics_path
        self._provider_weights = provider_weights
        self._sequential_executor = SequentialAttemptExecutor(self._run_single)
        self._parallel_executor = ParallelAttemptExecutor(
            self._run_single,
            normalize_concurrency,
            run_parallel_all_sync=run_parallel_all_sync,
            run_parallel_any_sync=run_parallel_any_sync,
            parallel_execution_error=ParallelExecutionError,
        )
        self._provider_executor = ProviderCallExecutor(backoff)
        self._active_provider_ids: tuple[str, ...] = ()
        self._current_attempt_index = 0

    def _run_provider_call(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        prompt: str,
    ) -> _ProviderCallResult:
        ensure_invoke_compat(provider)
        return self._provider_executor.execute(provider_config, provider, prompt)

    def run_sequential_attempt(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        self._active_provider_ids = tuple(cfg.provider for cfg, _ in providers)
        self._current_attempt_index = attempt_index
        return self._sequential_executor.run(
            providers,
            task,
            attempt_index,
            mode,
        )

    def run_parallel_attempt(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        self._active_provider_ids = tuple(cfg.provider for cfg, _ in providers)
        self._current_attempt_index = attempt_index
        return self._parallel_executor.run(
            providers,
            task,
            attempt_index,
            config,
        )

    def _run_single(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> SingleRunResult:
        prompt = task.render_prompt()
        shadow_session = open_shadow_session(self._shadow_provider, provider_config, prompt)
        provider_result = execute_provider_with_retries(
            self._provider_executor,
            provider_config,
            provider,
            prompt,
            token_bucket=self._token_bucket,
        )
        shadow_result, fallback_shadow_id = close_shadow_session(shadow_session)
        return build_single_run_result(
            provider_config=provider_config,
            task=task,
            attempt_index=attempt_index,
            mode=mode,
            provider_result=provider_result,
            evaluate_budget=self._evaluate_budget,
            build_metrics=self._build_metrics,
            schema_validator=self._schema_validator,
            shadow_result=shadow_result,
            fallback_shadow_id=fallback_shadow_id,
            active_provider_ids=self._active_provider_ids,
            current_attempt_index=self._current_attempt_index,
        )

__all__ = [
    "RunnerExecution",
    "SequentialAttemptExecutor",
    "ParallelAttemptExecutor",
    "SingleRunResult",
    "_SchemaValidator",
    "_TokenBucket",
]

sleep = _retry_sleep
