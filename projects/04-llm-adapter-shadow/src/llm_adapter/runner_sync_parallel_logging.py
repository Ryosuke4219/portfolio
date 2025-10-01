"""Helpers for logging parallel synchronous provider execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import CancelledError

from .observability import EventLogger
from .provider_spi import ProviderRequest, ProviderSPI
from .runner_shared import estimate_cost, log_provider_call, log_run_metric
from .runner_sync_invocation import ProviderInvocationResult
from .utils import elapsed_ms


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
    "CancelledResultsBuilder",
    "ParallelResultLogger",
]
