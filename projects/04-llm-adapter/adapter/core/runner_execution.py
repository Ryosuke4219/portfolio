"""CompareRunner の実行責務と実行戦略を提供するユーティリティ。"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Literal, Protocol, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.parallel_exec import (
        ParallelExecutionError,
        run_parallel_all_sync,
        run_parallel_any_sync,
    )

else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.parallel_exec import (
            ParallelExecutionError,
            run_parallel_all_sync,
            run_parallel_any_sync,
        )
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        T = TypeVar("T")

        class ParallelExecutionError(RuntimeError):
            """並列実行時エラーのフォールバック。"""

        def run_parallel_all_sync(
            workers: Sequence[Callable[[], T]], *, max_concurrency: int | None = None
        ) -> list[T]:
            return [worker() for worker in workers]

        def run_parallel_any_sync(
            workers: Sequence[Callable[[], T]], *, max_concurrency: int | None = None
        ) -> T:
            last_error: Exception | None = None
            for worker in workers:
                try:
                    return worker()
                except Exception as exc:  # pragma: no cover - テスト環境でのみ到達
                    last_error = exc
            if last_error is not None:
                raise ParallelExecutionError(str(last_error)) from last_error
            raise ParallelExecutionError("no worker executed successfully")

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        class ProviderSPI(Protocol):
            """プロバイダ SPI フォールバック."""

from .config import ProviderConfig
from .datasets import GoldenTask
from .execution.guards import _SchemaValidator, _TokenBucket
from .execution.provider_invoker import _ProviderCallResult, ProviderInvoker
from .execution.shadow_runner import ShadowRunner, ShadowRunnerResult
from .metrics import BudgetSnapshot, estimate_cost, RunMetrics
from .providers import BaseProvider, ProviderResponse

LOGGER = logging.getLogger(__name__)

@dataclass(slots=True)
class SingleRunResult:
    metrics: RunMetrics
    raw_output: str
    stop_reason: str | None = None
    aggregate_output: str | None = None
    error: Exception | None = None
    backoff_next_provider: bool = False
if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import BackoffPolicy, RunnerConfig


from .runner_execution_attempts import (  # noqa: E402  # isort: skip
    ParallelAttemptExecutor,
    SequentialAttemptExecutor,
)


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
        self._shadow_provider = shadow_provider
        self._metrics_path = metrics_path
        self._provider_weights = provider_weights
        self._provider_invoker = ProviderInvoker(backoff=backoff)
        self._sequential_executor = SequentialAttemptExecutor(self._run_single)
        self._parallel_executor = ParallelAttemptExecutor(
            self._run_single,
            normalize_concurrency,
            run_parallel_all_sync=run_parallel_all_sync,
            run_parallel_any_sync=run_parallel_any_sync,
            parallel_execution_error=ParallelExecutionError,
        )
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
        shadow_runner = ShadowRunner(self._shadow_provider)
        shadow_runner.start(provider_config, prompt)
        provider_result = self._provider_invoker.run(
            provider_config,
            provider,
            prompt,
        )
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
        shadow_result = shadow_runner.finalize()
        self._finalize_run_metrics(
            run_metrics,
            attempt_index,
            provider_result,
            response,
            status,
            failure_kind,
            error_message,
            schema_error,
            shadow_result,
            shadow_runner.provider_id,
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

    def _finalize_run_metrics(
        self,
        run_metrics: RunMetrics,
        attempt_index: int,
        provider_result: _ProviderCallResult,
        response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
        schema_error: str | None,
        shadow_result: ShadowRunnerResult | None,
        fallback_shadow_id: str | None,
    ) -> None:
        provider_ids: list[str] = []
        for provider_id in self._active_provider_ids:
            if provider_id not in provider_ids:
                provider_ids.append(provider_id)
        run_metrics.providers = provider_ids
        usage = response.token_usage
        prompt_tokens = int(getattr(usage, "prompt", response.input_tokens))
        completion_tokens = int(getattr(usage, "completion", response.output_tokens))
        total_tokens = int(getattr(usage, "total", prompt_tokens + completion_tokens))
        run_metrics.token_usage = {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
        }
        run_metrics.attempts = attempt_index + 1
        run_metrics.error_type = (
            type(provider_result.error).__name__ if provider_result.error else None
        )
        run_metrics.retries = max(self._current_attempt_index, 0) + max(
            provider_result.retries - 1, 0
        )
        if schema_error:
            run_metrics.status = status
            run_metrics.failure_kind = failure_kind
            run_metrics.error_message = error_message
        run_metrics.outcome = self._resolve_outcome(run_metrics.status)
        self._apply_shadow_metrics(run_metrics, shadow_result, fallback_shadow_id)

    def _apply_shadow_metrics(
        self,
        run_metrics: RunMetrics,
        shadow_result: ShadowRunnerResult | None,
        fallback_shadow_id: str | None,
    ) -> None:
        if shadow_result is None:
            if fallback_shadow_id is not None:
                run_metrics.shadow_provider_id = fallback_shadow_id
            return
        provider_id = shadow_result.provider_id or fallback_shadow_id
        if provider_id is not None:
            run_metrics.shadow_provider_id = provider_id
        if shadow_result.latency_ms is not None:
            run_metrics.shadow_latency_ms = int(shadow_result.latency_ms)
        if shadow_result.status is not None:
            run_metrics.shadow_status = shadow_result.status
            run_metrics.shadow_outcome = self._resolve_outcome(shadow_result.status)
        if shadow_result.error_message is not None:
            run_metrics.shadow_error_message = shadow_result.error_message

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

    @staticmethod
    def _resolve_outcome(status: str) -> Literal["success", "skip", "error"]:
        if status == "ok":
            return "success"
        if status == "skip":
            return "skip"
        return "error"


__all__ = [
    "RunnerExecution",
    "SequentialAttemptExecutor",
    "ParallelAttemptExecutor",
    "SingleRunResult",
    "_SchemaValidator",
    "_TokenBucket",
]
