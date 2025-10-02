"""Helpers for synchronous runner invocations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import cast, Literal, overload, Protocol, TYPE_CHECKING

from .errors import ProviderSkip
from .observability import EventLogger
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_shared import (
    log_provider_call,
    log_provider_skipped,
    MetricsPath,
    RateLimiter,
)
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow, ShadowMetrics
from .utils import elapsed_ms

if TYPE_CHECKING:
    from .runner_sync_parallel_logging import (
        CancelledResultsBuilder,
        ParallelResultLogger,
    )


class _RunWithShadowCallable(Protocol):
    @overload
    def __call__(
        self,
        primary: ProviderSPI,
        shadow: ProviderSPI | None,
        request: ProviderRequest,
        metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
        *,
        logger: EventLogger | None = None,
        capture_metrics: Literal[True],
    ) -> tuple[ProviderResponse, ShadowMetrics | None]: ...

    @overload
    def __call__(
        self,
        primary: ProviderSPI,
        shadow: ProviderSPI | None,
        request: ProviderRequest,
        metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
        *,
        logger: EventLogger | None = None,
        capture_metrics: Literal[False] = False,
    ) -> ProviderResponse: ...

    def __call__(
        self,
        primary: ProviderSPI,
        shadow: ProviderSPI | None,
        request: ProviderRequest,
        metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
        *,
        logger: EventLogger | None = None,
        capture_metrics: bool = False,
    ) -> ProviderResponse | tuple[ProviderResponse, ShadowMetrics | None]: ...


_DEFAULT_RUN_WITH_SHADOW = cast(_RunWithShadowCallable, run_with_shadow)


@dataclass(slots=True)
class ProviderInvocationResult:
    provider: ProviderSPI
    attempt: int
    total_providers: int
    response: ProviderResponse | None
    error: Exception | None
    latency_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    shadow_metrics: ShadowMetrics | None
    shadow_metrics_extra: dict[str, object] | None
    provider_call_logged: bool


class ProviderInvoker:
    """Invoke providers while capturing metrics."""

    def __init__(
        self,
        *,
        rate_limiter: RateLimiter | None,
        run_with_shadow: _RunWithShadowCallable = _DEFAULT_RUN_WITH_SHADOW,
        log_provider_call: Callable[..., None] = log_provider_call,
        log_provider_skipped: Callable[..., None] = log_provider_skipped,
        time_fn: Callable[[], float] = time.time,
        elapsed_ms: Callable[[float], int] = elapsed_ms,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._run_with_shadow = run_with_shadow
        self._log_provider_call = log_provider_call
        self._log_provider_skipped = log_provider_skipped
        self._time_fn = time_fn
        self._elapsed_ms = elapsed_ms

    def invoke(
        self,
        provider: ProviderSPI,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        event_logger: EventLogger | None,
        request_fingerprint: str,
        metadata: Mapping[str, object],
        shadow: ProviderSPI | None,
        metrics_path: MetricsPath,
        capture_shadow_metrics: bool,
    ) -> ProviderInvocationResult:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        attempt_started = self._time_fn()
        response: ProviderResponse | None = None
        error: Exception | None = None
        tokens_in: int | None = None
        tokens_out: int | None = None
        shadow_metrics: ShadowMetrics | None = None
        try:
            if capture_shadow_metrics:
                response, shadow_metrics = self._run_with_shadow(
                    provider,
                    shadow,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=True,
                )
            else:
                response = self._run_with_shadow(
                    provider,
                    shadow,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=False,
                )
        except Exception as exc:  # noqa: BLE001
            error = exc
            latency_ms = self._elapsed_ms(attempt_started)
            if isinstance(exc, ProviderSkip):
                self._log_provider_skipped(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt,
                    total_providers=total_providers,
                    error=exc,
                )
        else:
            latency_ms = response.latency_ms
            usage = response.token_usage
            tokens_in = usage.prompt
            tokens_out = usage.completion
        status = "ok" if error is None else "error"
        self._log_provider_call(
            event_logger,
            request_fingerprint=request_fingerprint,
            provider=provider,
            request=request,
            attempt=attempt,
            total_providers=total_providers,
            status=status,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
            metadata=metadata,
            shadow_used=shadow is not None,
        )
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=response,
            error=error,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            shadow_metrics=shadow_metrics,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )


def _load_parallel_logging() -> tuple[
    type["CancelledResultsBuilder"],
    type["ParallelResultLogger"],
]:
    from .runner_sync_parallel_logging import (
        CancelledResultsBuilder as _CancelledResultsBuilder,
        ParallelResultLogger as _ParallelResultLogger,
    )

    return _CancelledResultsBuilder, _ParallelResultLogger


if not TYPE_CHECKING:
    CancelledResultsBuilder, ParallelResultLogger = _load_parallel_logging()


__all__ = [
    "ProviderInvocationResult",
    "ProviderInvoker",
    "CancelledResultsBuilder",
    "ParallelResultLogger",
]
