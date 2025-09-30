"""CompareRunner の実行責務と実行戦略を提供するユーティリティ。"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Thread
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
from .errors import (
    AuthError,
    ConfigError,
    ProviderSkip,
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from .execution.guards import _SchemaValidator, _TokenBucket
from .metrics import BudgetSnapshot, estimate_cost, RunMetrics
from .provider_spi import ProviderRequest
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
        shadow_thread: Thread | None = None
        shadow_result: dict[str, object] | None = None
        shadow_provider_id: str | None = None
        if self._shadow_provider is not None:
            shadow_provider = self._shadow_provider
            try:
                shadow_provider_id = shadow_provider.name()
            except Exception:  # pragma: no cover - name() 実装の防御
                shadow_provider_id = None
            request = ProviderRequest(
                model=provider_config.model,
                prompt=prompt,
                max_tokens=provider_config.max_tokens,
                temperature=provider_config.temperature,
                top_p=provider_config.top_p,
                timeout_s=float(provider_config.timeout_s) if provider_config.timeout_s > 0 else None,
            )
            shadow_data: dict[str, object] = {}

            def _run_shadow() -> None:
                start = perf_counter()
                try:
                    response = shadow_provider.invoke(request)
                except Exception as exc:  # pragma: no cover - 影響範囲縮小のため
                    latency_ms = int((perf_counter() - start) * 1000)
                    LOGGER.exception("Shadow provider %s failed", shadow_provider_id, exc_info=exc)
                    shadow_data.update(
                        provider_id=shadow_provider_id,
                        latency_ms=latency_ms,
                        status="error",
                        error_message=str(exc),
                    )
                else:
                    latency_ms = int(getattr(response, "latency_ms", 0))
                    LOGGER.info(
                        "Shadow provider %s completed in %sms", shadow_provider_id, latency_ms
                    )
                    shadow_data.update(
                        provider_id=shadow_provider_id,
                        latency_ms=latency_ms,
                        status="ok",
                    )
                finally:
                    shadow_data.setdefault(
                        "latency_ms", int((perf_counter() - start) * 1000)
                    )

            shadow_thread = Thread(
                target=_run_shadow,
                name=f"shadow-{shadow_provider_id or 'unknown'}",
                daemon=True,
            )
            shadow_thread.start()
            shadow_result = shadow_data
        provider_result = self._run_provider_call(
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
        if shadow_thread is not None:
            shadow_thread.join()
            if shadow_result:
                provider_key = shadow_result.get("provider_id")
                run_metrics.shadow_provider_id = (
                    str(provider_key)
                    if provider_key is not None
                    else shadow_provider_id
                )
                latency_val = shadow_result.get("latency_ms")
                if latency_val is not None:
                    run_metrics.shadow_latency_ms = int(latency_val)
                status_val = shadow_result.get("status")
                if isinstance(status_val, str):
                    run_metrics.shadow_status = status_val
                    run_metrics.shadow_outcome = self._resolve_outcome(status_val)
                error_val = shadow_result.get("error_message")
                if isinstance(error_val, str):
                    run_metrics.shadow_error_message = error_val
            elif shadow_provider_id is not None:
                run_metrics.shadow_provider_id = shadow_provider_id
        return SingleRunResult(
            metrics=run_metrics,
            raw_output=raw_output,
            stop_reason=stop_reason,
            error=provider_result.error,
            backoff_next_provider=provider_result.backoff_next_provider,
        )

    def _run_provider_call(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        prompt: str,
    ) -> _ProviderCallResult:
        result = self._invoke_provider(provider, prompt)
        status, failure_kind = self._check_timeout(
            provider_config, result.latency_ms, result.status, result.failure_kind
        )
        status, failure_kind = self._enforce_output_guard(
            result.response.output_text, status, failure_kind
        )
        result.status = status
        result.failure_kind = failure_kind
        return result

    def _build_error_result(
        self,
        prompt: str,
        started_at: float,
        error: Exception,
        *,
        status: str,
        failure_kind: str,
        advance: bool,
    ) -> _ProviderCallResult:
        latency_ms = int((perf_counter() - started_at) * 1000)
        response = self._build_error_response(prompt, latency_ms)
        return _ProviderCallResult(
            response=response,
            status=status,
            failure_kind=failure_kind,
            error_message=str(error),
            latency_ms=latency_ms,
            retries=1,
            error=error,
            backoff_next_provider=advance,
        )

    def _handle_backoff_error(
        self,
        prompt: str,
        started_at: float,
        error: Exception,
        *,
        status: str,
        failure_kind: str,
        default_advance: bool,
    ) -> _ProviderCallResult:
        advance = self._apply_backoff(error)
        if not advance:
            advance = default_advance
        return self._build_error_result(
            prompt,
            started_at,
            error,
            status=status,
            failure_kind=failure_kind,
            advance=advance,
        )

    def _build_error_response(self, prompt: str, latency_ms: int) -> ProviderResponse:
        return ProviderResponse(
            output_text="",
            input_tokens=len(prompt.split()),
            output_tokens=0,
            latency_ms=latency_ms,
        )

    def _apply_backoff(self, error: Exception) -> bool:
        policy = self._backoff
        if policy is None:
            return False
        should_advance = False
        delay = 0.0
        if isinstance(error, RateLimitError):
            delay = float(policy.rate_limit_sleep_s or 0.0)
            should_advance = True
        elif isinstance(error, TimeoutError):
            should_advance = bool(policy.timeout_next_provider)
        elif isinstance(error, RetriableError):
            should_advance = bool(policy.retryable_next_provider)
        if delay > 0.0:
            sleep(delay)
        return should_advance

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

    def _invoke_provider(
        self, provider: BaseProvider, prompt: str
    ) -> _ProviderCallResult:
        start = perf_counter()
        try:
            response = provider.generate(prompt)
        except ProviderSkip as exc:
            latency_ms = int((perf_counter() - start) * 1000)
            response = self._build_error_response(prompt, latency_ms)
            return _ProviderCallResult(
                response=response,
                status="skip",
                failure_kind="skip",
                error_message=str(exc),
                latency_ms=latency_ms,
                retries=1,
                error=exc,
                backoff_next_provider=True,
            )
        except AuthError as exc:
            return self._build_error_result(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="auth",
                advance=True,
            )
        except ConfigError as exc:
            return self._build_error_result(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="config",
                advance=True,
            )
        except RateLimitError as exc:
            return self._handle_backoff_error(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="rate_limit",
                default_advance=True,
            )
        except TimeoutError as exc:
            return self._handle_backoff_error(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="timeout",
                default_advance=False,
            )
        except RetriableError as exc:
            return self._handle_backoff_error(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="retryable",
                default_advance=False,
            )
        except Exception as exc:  # pragma: no cover - 実プロバイダ利用時の防御
            return self._build_error_result(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="provider_error",
                advance=False,
            )
        latency_ms = response.latency_ms
        return _ProviderCallResult(
            response=response,
            status="ok",
            failure_kind=None,
            error_message=None,
            latency_ms=latency_ms,
            retries=1,
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
@dataclass(slots=True)
class _ProviderCallResult:
    response: ProviderResponse
    status: str
    failure_kind: str | None
    error_message: str | None
    latency_ms: int
    retries: int
    error: Exception | None = None
    backoff_next_provider: bool = False
