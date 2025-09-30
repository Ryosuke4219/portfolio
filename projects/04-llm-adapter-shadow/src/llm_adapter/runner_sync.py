"""Synchronous runner implementation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import time
from typing import cast

from .errors import (
    FatalError,
    ProviderSkip,
)
from .observability import EventLogger
from .parallel_exec import (
    ParallelAllResult,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerConfig
from .runner_shared import (
    estimate_cost,
    log_provider_call,
    log_provider_skipped,
    log_run_metric,
    MetricsPath,
    RateLimiter,
    resolve_event_logger,
    resolve_rate_limiter,
)
from .runner_sync_modes import get_sync_strategy, SyncRunContext
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow, ShadowMetrics
from .utils import content_hash, elapsed_ms


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


class Runner:
    """Attempt providers sequentially until one succeeds."""

    def __init__(
        self,
        providers: Sequence[ProviderSPI],
        logger: EventLogger | None = None,
        *,
        config: RunnerConfig | None = None,
    ) -> None:
        if not providers:
            raise ValueError("Runner requires at least one provider")
        self.providers: list[ProviderSPI] = list(providers)
        self._logger = logger
        self._config = config or RunnerConfig()
        self._rate_limiter: RateLimiter | None = resolve_rate_limiter(self._config.rpm)

    def _invoke_provider_sync(
        self,
        provider: ProviderSPI,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        event_logger: EventLogger | None,
        request_fingerprint: str,
        metadata: dict[str, object],
        shadow: ProviderSPI | None,
        metrics_path: MetricsPath,
        capture_shadow_metrics: bool,
    ) -> ProviderInvocationResult:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        attempt_started = time.time()
        response: ProviderResponse | None = None
        error: Exception | None = None
        latency_ms: int
        tokens_in: int | None = None
        tokens_out: int | None = None
        shadow_metrics: ShadowMetrics | None = None
        try:
            if capture_shadow_metrics:
                response_with_metrics = run_with_shadow(
                    provider,
                    shadow,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=True,
                )
                response, shadow_metrics = cast(
                    tuple[ProviderResponse, ShadowMetrics | None],
                    response_with_metrics,
                )
            else:
                response_only = run_with_shadow(
                    provider,
                    shadow,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=False,
                )
                response = cast(ProviderResponse, response_only)
        except Exception as exc:  # noqa: BLE001
            error = exc
            latency_ms = elapsed_ms(attempt_started)
            if isinstance(exc, ProviderSkip):
                log_provider_skipped(
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
        log_provider_call(
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
        )

    def _log_parallel_results(
        self,
        results: Sequence[ProviderInvocationResult | None],
        *,
        event_logger: EventLogger | None,
        request: ProviderRequest,
        request_fingerprint: str,
        metadata: dict[str, object],
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
                cost_usd = estimate_cost(result.provider, tokens_in, tokens_out)
            else:
                tokens_in = None
                tokens_out = None
                cost_usd = 0.0
            latency_ms = result.latency_ms
            if latency_ms is None:
                latency_ms = elapsed_ms(run_started)
            attempts_value = attempts_map.get(result.attempt, result.attempt)
            log_run_metric(
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
                error=None if status == "ok" else result.error,
                metadata=metadata,
                shadow_used=shadow_used,
            )

    def _extract_fatal_error(
        self, results: Sequence[ProviderInvocationResult | None]
    ) -> FatalError | None:
        for result in results:
            if result is None:
                continue
            error = result.error
            if isinstance(error, FatalError):
                return error
        return None

    def run(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        """Execute ``request`` with fallback semantics."""

        event_logger, metrics_path_str = resolve_event_logger(
            self._logger, shadow_metrics_path
        )
        metadata = dict(request.metadata or {})
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )
        shadow_used = shadow is not None
        strategy = get_sync_strategy(self._config.mode)
        context = SyncRunContext(
            runner=self,
            request=request,
            event_logger=event_logger,
            metadata=metadata,
            run_started=run_started,
            request_fingerprint=request_fingerprint,
            shadow=shadow,
            shadow_used=shadow_used,
            metrics_path=metrics_path_str,
            run_parallel_all=run_parallel_all_sync,
            run_parallel_any=run_parallel_any_sync,
        )
        return strategy.execute(context)


__all__ = ["Runner"]
