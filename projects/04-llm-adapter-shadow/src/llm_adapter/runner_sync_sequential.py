"""Sequential synchronous runner strategy implementation."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import NoReturn, TYPE_CHECKING

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
from .parallel_exec import ParallelAllResult
from .provider_spi import ProviderResponse, ProviderSPI
from .runner_shared import error_family, estimate_cost, log_run_metric
from .utils import elapsed_ms

if TYPE_CHECKING:
    from .runner_sync import ProviderInvocationResult
    from .runner_sync_modes import SyncRunContext


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
        latency_ms = (
            result.latency_ms
            if result.latency_ms is not None
            else response.latency_ms
        )
        metadata_with_shadow: Mapping[str, object]
        if result.shadow_metrics_extra:
            merged_metadata = dict(self._context.metadata)
            merged_metadata.update(result.shadow_metrics_extra)
            metadata_with_shadow = merged_metadata
        else:
            metadata_with_shadow = self._context.metadata
        log_run_metric(
            self._event_logger,
            request_fingerprint=self._context.request_fingerprint,
            request=self._context.request,
            provider=provider,
            status="ok",
            attempts=attempt,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            error=None,
            metadata=metadata_with_shadow,
            shadow_used=self._context.shadow_used,
        )
        return response

    def handle_failure(
        self,
        provider: ProviderSPI,
        attempt: int,
        result: ProviderInvocationResult,
    ) -> None:
        error = result.error
        if error is None:
            return
        self._last_error = error
        summary = f"{type(error).__name__}: {error}"
        self._failure_details.append(
            {
                "provider": provider.name(),
                "attempt": str(attempt),
                "summary": summary,
            }
        )
        tokens_in = result.tokens_in
        tokens_out = result.tokens_out
        latency_ms = (
            result.latency_ms
            if result.latency_ms is not None
            else elapsed_ms(self._context.run_started)
        )
        metadata_with_shadow: Mapping[str, object]
        if result.shadow_metrics_extra:
            merged_metadata = dict(self._context.metadata)
            merged_metadata.update(result.shadow_metrics_extra)
            metadata_with_shadow = merged_metadata
        else:
            metadata_with_shadow = self._context.metadata
        log_run_metric(
            self._event_logger,
            request_fingerprint=self._context.request_fingerprint,
            request=self._context.request,
            provider=provider,
            status="error",
            attempts=attempt,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
            error=error,
            metadata=metadata_with_shadow,
            shadow_used=self._context.shadow_used,
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
                    "providers": [
                        provider.name() for provider in self._runner.providers
                    ],
                    "last_error_type": (
                        type(self._last_error).__name__ if self._last_error else None
                    ),
                    "last_error_message": (
                        str(self._last_error) if self._last_error else None
                    ),
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
        metric_error = (
            self._last_error if self._last_error is not None else failure_error
        )
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
    ) -> (
        ProviderResponse | ParallelAllResult[ProviderInvocationResult, ProviderResponse]
    ):
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

            if result.error is None:
                continue
            tracker.handle_failure(provider, attempt_index, result)

        tracker.finalize_and_raise()


__all__ = ["_SequentialRunTracker", "SequentialStrategy"]
