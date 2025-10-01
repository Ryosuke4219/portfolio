"""Synchronous runner strategy implementations."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

from .errors import (
    AllFailedError,
    AuthError,
    ConfigError,
    FatalError,
    ProviderSkip,
    RateLimitError,
    RetryableError,
    SkipError,
    TimeoutError,
)
from .observability import EventLogger
from .parallel_exec import ParallelAllResult, ParallelExecutionError
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerMode
from .runner_shared import error_family, estimate_cost, log_run_metric, MetricsPath
from .utils import elapsed_ms

if TYPE_CHECKING:
    from .runner_sync import ProviderInvocationResult, Runner


class ParallelAllCallable(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], ProviderInvocationResult]],
        *,
        max_concurrency: int | None = ...,
    ) -> Sequence[ProviderInvocationResult]:
        ...


class ParallelAnyCallable(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], ProviderInvocationResult]],
        *,
        max_concurrency: int | None = ...,
        on_cancelled: Callable[[Sequence[int]], None] | None = ...,
    ) -> ProviderInvocationResult:
        ...


@dataclass(slots=True)
class SyncRunContext:
    runner: Runner
    request: ProviderRequest
    event_logger: EventLogger | None
    metadata: dict[str, object]
    run_started: float
    request_fingerprint: str
    shadow: ProviderSPI | None
    shadow_used: bool
    metrics_path: MetricsPath
    run_parallel_all: ParallelAllCallable
    run_parallel_any: ParallelAnyCallable


class SyncRunStrategy(Protocol):
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        ...


def _limited_providers(
    providers: Sequence[ProviderSPI], max_attempts: int | None
) -> Sequence[ProviderSPI]:
    if max_attempts is None:
        return providers
    if max_attempts <= 0:
        return ()
    return providers[:max_attempts]


def _raise_no_attempts(context: SyncRunContext) -> None:
    event_logger = context.event_logger
    runner = context.runner
    error = AllFailedError("no providers were attempted", failures=[])
    if event_logger is not None:
        event_logger.emit(
            "provider_chain_failed",
            {
                "request_fingerprint": context.request_fingerprint,
                "provider_attempts": 0,
                "providers": [provider.name() for provider in runner.providers],
                "last_error_type": None,
                "last_error_message": None,
                "last_error_family": None,
            },
        )
    log_run_metric(
        event_logger,
        request_fingerprint=context.request_fingerprint,
        request=context.request,
        provider=None,
        status="error",
        attempts=0,
        latency_ms=elapsed_ms(context.run_started),
        tokens_in=None,
        tokens_out=None,
        cost_usd=0.0,
        error=error,
        metadata=context.metadata,
        shadow_used=context.shadow_used,
    )
    raise error


class _SequentialRunTracker:
    def __init__(self, context: SyncRunContext) -> None:
        self._context = context
        self._runner = context.runner
        self._config = context.runner._config
        self._event_logger = context.event_logger
        self._last_error: Exception | None = None
        self._failure_details: list[dict[str, str]] = []
        self.attempt_count = 0

    def record_attempt(self, attempt: int) -> None:
        self.attempt_count = attempt

    def handle_success(
        self,
        provider: ProviderSPI,
        attempt: int,
        result: ProviderInvocationResult,
    ) -> ProviderResponse | None:
        response = result.response
        if response is None:
            return None
        tokens_in = result.tokens_in if result.tokens_in is not None else 0
        tokens_out = result.tokens_out if result.tokens_out is not None else 0
        cost_usd = estimate_cost(provider, tokens_in, tokens_out)
        log_run_metric(
            self._event_logger,
            request_fingerprint=self._context.request_fingerprint,
            request=self._context.request,
            provider=provider,
            status="ok",
            attempts=attempt,
            latency_ms=elapsed_ms(self._context.run_started),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            error=None,
            metadata=self._context.metadata,
            shadow_used=self._context.shadow_used,
        )
        return response

    def handle_failure(
        self,
        provider: ProviderSPI,
        attempt: int,
        error: Exception,
    ) -> None:
        self._last_error = error
        summary = f"{type(error).__name__}: {error}"
        self._failure_details.append(
            {
                "provider": provider.name(),
                "attempt": str(attempt),
                "summary": summary,
            }
        )
        if isinstance(error, FatalError):
            if isinstance(error, AuthError | ConfigError):
                if self._event_logger is not None:
                    self._event_logger.emit(
                        "provider_fallback",
                        {
                            "request_fingerprint": self._context.request_fingerprint,
                            "provider": provider.name(),
                            "attempt": attempt,
                            "error_type": type(error).__name__,
                            "error_message": str(error),
                        },
                    )
                return
            raise error
        if isinstance(error, RateLimitError):
            sleep_duration = self._config.backoff.rate_limit_sleep_s
            if sleep_duration > 0:
                time.sleep(sleep_duration)
            return
        if isinstance(error, RetryableError):
            if isinstance(error, TimeoutError):
                if not self._config.backoff.timeout_next_provider:
                    raise error
                return
            if self._config.backoff.retryable_next_provider:
                return
            raise error
        if isinstance(error, SkipError | ProviderSkip):
            return
        raise error

    def finalize_and_raise(self) -> NoReturn:
        event_logger = self._event_logger
        if event_logger is not None:
            event_logger.emit(
                "provider_chain_failed",
                {
                    "request_fingerprint": self._context.request_fingerprint,
                    "provider_attempts": self.attempt_count,
                    "providers": [provider.name() for provider in self._runner.providers],
                    "last_error_type": type(self._last_error).__name__ if self._last_error else None,
                    "last_error_message": str(self._last_error) if self._last_error else None,
                    "last_error_family": error_family(self._last_error),
                },
            )
        detail_text = "; ".join(
            f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
            for item in self._failure_details
        )
        message = "all providers failed"
        if detail_text:
            message = f"{message}: {detail_text}"
        failure_error = AllFailedError(message, failures=self._failure_details)
        metric_error = self._last_error if self._last_error is not None else failure_error
        log_run_metric(
            event_logger,
            request_fingerprint=self._context.request_fingerprint,
            request=self._context.request,
            provider=None,
            status="error",
            attempts=self.attempt_count,
            latency_ms=elapsed_ms(self._context.run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=metric_error,
            metadata=self._context.metadata,
            shadow_used=self._context.shadow_used,
        )
        if self._last_error is not None:
            raise failure_error from self._last_error
        raise failure_error


class SequentialStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        config = runner._config
        max_attempts = config.max_attempts
        tracker = _SequentialRunTracker(context)

        for loop_index, provider in enumerate(runner.providers, start=1):
            if max_attempts is not None and loop_index > max_attempts:
                break
            attempt_index = loop_index
            tracker.record_attempt(attempt_index)
            result = runner._invoke_provider_sync(
                provider,
                context.request,
                attempt=attempt_index,
                total_providers=len(runner.providers),
                event_logger=context.event_logger,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                shadow=context.shadow,
                metrics_path=context.metrics_path,
                capture_shadow_metrics=False,
            )
            response = tracker.handle_success(provider, attempt_index, result)
            if response is not None:
                return response

            error = result.error
            if error is None:
                continue
            tracker.handle_failure(provider, attempt_index, error)

        tracker.finalize_and_raise()


class ParallelAnyStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        total_providers = len(runner.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = _limited_providers(runner.providers, max_attempts)

        def make_worker(index: int, provider: ProviderSPI) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=False,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            _raise_no_attempts(context)

        attempts_override: dict[int, int] | None = None
        cancelled_slots: tuple[int, ...] = ()

        def _record_cancelled(indices: Sequence[int]) -> None:
            nonlocal cancelled_slots
            cancelled_slots = tuple(indices)

        try:
            winner = context.run_parallel_any(
                workers,
                max_concurrency=runner._config.max_concurrency,
                on_cancelled=_record_cancelled,
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            response = winner.response
            if response is None:
                raise ParallelExecutionError("all workers failed")
            attempts_final = sum(1 for item in results if item is not None)
            if attempts_final == 0:
                attempts_final = winner.attempt
            attempts_override = {winner.attempt: attempts_final}
            return response
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            if cancelled_slots:
                runner._apply_cancelled_results(
                    results,
                    providers=providers,
                    cancelled_indices=cancelled_slots,
                    total_providers=total_providers,
                    run_started=context.run_started,
                )
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
                attempts_override=attempts_override,
            )


class ParallelAllStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        total_providers = len(runner.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = _limited_providers(runner.providers, max_attempts)

        def make_worker(index: int, provider: ProviderSPI) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=False,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            _raise_no_attempts(context)

        try:
            invocations = context.run_parallel_all(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            for invocation in invocations:
                if invocation.response is None:
                    raise ParallelExecutionError("all workers failed")
            return ParallelAllResult(
                invocations,
                lambda invocation: cast(ProviderResponse, invocation.response),
            )
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
            )


# Imported at the end to avoid circular dependency with ConsensusStrategy helper imports.
from .runner_sync_consensus import ConsensusStrategy  # noqa: E402


def get_sync_strategy(mode: RunnerMode) -> SyncRunStrategy:
    if mode == RunnerMode.SEQUENTIAL:
        return SequentialStrategy()
    if mode == RunnerMode.PARALLEL_ANY:
        return ParallelAnyStrategy()
    if mode == RunnerMode.PARALLEL_ALL:
        return ParallelAllStrategy()
    if mode == RunnerMode.CONSENSUS:
        return ConsensusStrategy()
    raise RuntimeError(f"Unsupported runner mode: {mode}")


__all__ = [
    "SyncRunContext",
    "SyncRunStrategy",
    "_limited_providers",
    "_raise_no_attempts",
    "get_sync_strategy",
]
