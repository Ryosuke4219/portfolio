"""CompareRunner の実行責務と実行戦略を提供するユーティリティ。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Protocol

from ._parallel_shim import (
    ParallelExecutionError,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from ._provider_execution import ProviderCallExecutor, _ProviderCallResult
from ._shadow_helpers import finalize_shadow_session, start_shadow_session
from .config import ProviderConfig
from .datasets import GoldenTask
from .errors import RateLimitError, RetryableError
from .execution.guards import _SchemaValidator, _TokenBucket
from .metrics import BudgetSnapshot, estimate_cost, finalize_run_metrics, RunMetrics
from .providers import BaseProvider, ProviderResponse
from .runner_execution_attempts import (
    ParallelAttemptExecutor,
    SequentialAttemptExecutor,
)

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    from .runner_api import BackoffPolicy, RunnerConfig
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック

        class ProviderSPI(Protocol):
            """プロバイダ SPI フォールバック."""

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


@dataclass(slots=True)
class SingleRunResult:
    metrics: RunMetrics
    raw_output: str
    stop_reason: str | None = None
    aggregate_output: str | None = None
    error: Exception | None = None
    backoff_next_provider: bool = False


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
        if self._token_bucket:
            self._token_bucket.acquire()
        prompt = task.render_prompt()
        shadow_session = start_shadow_session(self._shadow_provider, provider_config, prompt)
        retries_config = provider_config.retries
        max_attempts = max(0, retries_config.max) + 1
        attempt = 0
        provider_result: _ProviderCallResult | None = None
        while attempt < max_attempts:
            attempt += 1
            provider_result = self._provider_executor.execute(provider_config, provider, prompt)
            provider_result.retries = attempt
            if provider_result.status == "ok":
                break
            error = provider_result.error
            if provider_result.backoff_next_provider:
                if isinstance(error, RateLimitError) and attempt < max_attempts:
                    pass
                else:
                    break
            if attempt >= max_attempts:
                break
            if not isinstance(error, RetryableError):
                break
            backoff_delay = float(retries_config.backoff_s or 0.0)
            if backoff_delay > 0.0:
                sleep(backoff_delay)
        if provider_result is None:  # pragma: no cover - defensive
            raise RuntimeError("provider call did not yield a result")
        response = provider_result.response
        status = provider_result.status
        failure_kind = provider_result.failure_kind
        error_message = provider_result.error_message
        latency_ms = provider_result.latency_ms
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
        status, failure_kind, error_message, schema_error = self._apply_schema_validation(
            response,
            status,
            failure_kind,
            error_message,
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
        shadow_result, fallback_shadow_id = finalize_shadow_session(shadow_session)
        finalize_run_metrics(
            run_metrics,
            attempt_index=attempt_index,
            provider_result=provider_result,
            response=response,
            status=status,
            failure_kind=failure_kind,
            error_message=error_message,
            schema_error=schema_error,
            shadow_result=shadow_result,
            fallback_shadow_id=fallback_shadow_id,
            active_provider_ids=self._active_provider_ids,
            current_attempt_index=self._current_attempt_index,
        )
        return self._build_single_run_result(
            run_metrics,
            raw_output,
            stop_reason,
            provider_result,
        )

    def _apply_schema_validation(
        self,
        response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[str, str | None, str | None, str | None]:
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
        return status, failure_kind, error_message, schema_error

    @staticmethod
    def _build_single_run_result(
        run_metrics: RunMetrics,
        raw_output: str,
        stop_reason: str | None,
        provider_result: _ProviderCallResult,
    ) -> SingleRunResult:
        return SingleRunResult(
            metrics=run_metrics,
            raw_output=raw_output,
            stop_reason=stop_reason,
            error=provider_result.error,
            backoff_next_provider=provider_result.backoff_next_provider,
        )


__all__ = [
    "RunnerExecution",
    "SequentialAttemptExecutor",
    "ParallelAttemptExecutor",
    "SingleRunResult",
    "_SchemaValidator",
    "_TokenBucket",
]
