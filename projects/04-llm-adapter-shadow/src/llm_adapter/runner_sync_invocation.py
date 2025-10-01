"""Helpers for synchronous runner invocations."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import CancelledError
from dataclasses import dataclass
import time
from typing import cast, runtime_checkable

from typing_extensions import Protocol

from .errors import ProviderSkip
from .observability import EventLogger
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_shared import (
    estimate_cost,
    log_provider_call,
    log_provider_skipped,
    log_run_metric,
    MetricsPath,
    RateLimiter,
)
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow, ShadowMetrics
from .utils import elapsed_ms


@runtime_checkable
class _RunWithShadowCallable(Protocol):
    def __call__(
        self,
        primary: ProviderSPI,
        shadow: ProviderSPI | None,
        request: ProviderRequest,
        metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
        *,
        logger: EventLogger | None = None,
        capture_metrics: bool = False,
    ) -> ProviderResponse | tuple[ProviderResponse, ShadowMetrics | None]:
        ...


_DEFAULT_RUN_WITH_SHADOW: _RunWithShadowCallable = cast(
    _RunWithShadowCallable, run_with_shadow
)

RunWithShadowParameter = _RunWithShadowCallable | Callable[
    ..., ProviderResponse | tuple[ProviderResponse, ShadowMetrics | None]
]


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
        run_with_shadow: RunWithShadowParameter = _DEFAULT_RUN_WITH_SHADOW,
        log_provider_call: Callable[..., None] = log_provider_call,
        log_provider_skipped: Callable[..., None] = log_provider_skipped,
        time_fn: Callable[[], float] = time.time,
        elapsed_ms: Callable[[float], int] = elapsed_ms,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._run_with_shadow = cast(_RunWithShadowCallable, run_with_shadow)
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
            result = self._run_with_shadow(
                provider,
                shadow,
                request,
                metrics_path=metrics_path,
                logger=event_logger,
                capture_metrics=capture_shadow_metrics,
            )
            if capture_shadow_metrics:
                response, shadow_metrics = cast(
                    tuple[ProviderResponse, ShadowMetrics | None],
                    result,
                )
            else:
                response = cast(ProviderResponse, result)
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


class CancelledResultsBuilder:
    """Construct cancelled results for providers that never executed."""

    def __init__(
        self,
        *,
        run_started: float,
        elapsed_ms: Callable[[float], int] = elapsed_ms,
    ) -> None:
        self._run_started = run_started
        self._elapsed_ms = elapsed_ms

    def build(
        self,
        *,
        provider: ProviderSPI,
        attempt: int,
        total_providers: int,
    ) -> ProviderInvocationResult:
        latency_ms = self._elapsed_ms(self._run_started)
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=None,
            error=CancelledError(),
            latency_ms=latency_ms,
            tokens_in=None,
            tokens_out=None,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=False,
        )

    def apply(
        self,
        results: list[ProviderInvocationResult | None],
        *,
        providers: Sequence[ProviderSPI],
        cancelled_indices: Sequence[int],
        total_providers: int,
    ) -> None:
        for index in cancelled_indices:
            if index < 0 or index >= len(providers):
                continue
            if index >= len(results):
                continue
            if results[index] is not None:
                continue
            provider = providers[index]
            results[index] = self.build(
                provider=provider,
                attempt=index + 1,
                total_providers=total_providers,
            )


class ParallelResultLogger:
    """Emit provider call and metric events for parallel execution results."""

    def __init__(
        self,
        *,
        log_provider_call: Callable[..., None] = log_provider_call,
        log_run_metric: Callable[..., None] = log_run_metric,
        estimate_cost: Callable[[object, int, int], float] = estimate_cost,
        elapsed_ms: Callable[[float], int] = elapsed_ms,
    ) -> None:
        self._log_provider_call = log_provider_call
        self._log_run_metric = log_run_metric
        self._estimate_cost = estimate_cost
        self._elapsed_ms = elapsed_ms

    def log_results(
        self,
        results: Sequence[ProviderInvocationResult | None],
        *,
        event_logger: EventLogger | None,
        request: ProviderRequest,
        request_fingerprint: str,
        metadata: Mapping[str, object],
        run_started: float,
        shadow_used: bool,
        skip: tuple[ProviderInvocationResult, ...] | None = None,
        attempts_override: Mapping[int, int] | None = None,
    ) -> None:
        skipped = skip or ()
        attempts_map = dict(attempts_override or {})
        for result in results:
            if result is None:
                continue
            if result.shadow_metrics is not None:
                result.shadow_metrics.emit(result.shadow_metrics_extra)
            if any(result is skipped_result for skipped_result in skipped):
                continue
            status = "ok" if result.response is not None else "error"
            if status == "ok":
                tokens_in = result.tokens_in if result.tokens_in is not None else 0
                tokens_out = result.tokens_out if result.tokens_out is not None else 0
                cost_usd = self._estimate_cost(result.provider, tokens_in, tokens_out)
                error_for_metric: Exception | None = None
            else:
                tokens_in = None
                tokens_out = None
                cost_usd = 0.0
                error_for_metric = result.error
            latency_ms = result.latency_ms
            if latency_ms is None:
                latency_ms = self._elapsed_ms(run_started)
            if not result.provider_call_logged:
                self._log_provider_call(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=result.provider,
                    request=request,
                    attempt=result.attempt,
                    total_providers=result.total_providers,
                    status=status,
                    latency_ms=latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    error=error_for_metric,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                result.provider_call_logged = True
            attempts_value = attempts_map.get(result.attempt, result.attempt)
            self._log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=result.provider,
                status=status,
                attempts=attempts_value,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                error=error_for_metric,
                metadata=metadata,
                shadow_used=shadow_used,
            )


__all__ = [
    "ProviderInvocationResult",
    "ProviderInvoker",
    "CancelledResultsBuilder",
    "ParallelResultLogger",
]

