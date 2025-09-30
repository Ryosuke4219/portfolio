"""CompareRunner の実行責務と実行戦略を提供するユーティリティ。"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
from time import perf_counter, sleep
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
from .metrics import BudgetSnapshot, estimate_cost, RunMetrics
from .providers import BaseProvider, ProviderResponse
from .runner_execution_attempts import (
    ParallelAttemptExecutor,
    SequentialAttemptExecutor,
)


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


@dataclass(slots=True)
class SingleRunResult:
    metrics: RunMetrics
    raw_output: str
    stop_reason: str | None = None
    aggregate_output: str | None = None
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
        run_metrics.retries = max(self._current_attempt_index, 0)
        if schema_error:
            run_metrics.status = status
            run_metrics.failure_kind = failure_kind
            run_metrics.error_message = error_message
        run_metrics.outcome = self._resolve_outcome(run_metrics.status)
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

    @staticmethod
    def _check_timeout(
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

    @staticmethod
    def _enforce_output_guard(
        output_text: str | None, status: str, failure_kind: str | None
    ) -> tuple[str, str | None]:
        if (output_text is None or not output_text.strip()) and status == "ok":
            return "error", failure_kind or "guard_violation"
        return status, failure_kind

    @staticmethod
    def _invoke_provider(
        provider: BaseProvider, prompt: str
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
            response = ProviderResponse(
                output_text="",
                input_tokens=len(prompt.split()),
                output_tokens=0,
                latency_ms=latency_ms,
            )
            return response, status, failure_kind, error_message, latency_ms
        return response, status, failure_kind, error_message, response.latency_ms

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
