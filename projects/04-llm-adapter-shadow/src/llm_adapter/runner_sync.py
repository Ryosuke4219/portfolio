"""Synchronous runner implementation."""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
import time
from typing import cast

from .errors import FatalError
from .observability import EventLogger
from .parallel_exec import (
    ParallelAllResult,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerConfig, RunnerMode
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
from .runner_sync_invocation import (
    _DEFAULT_RUN_WITH_SHADOW,
    CancelledResultsBuilder,
    ParallelResultLogger,
    ProviderInvocationResult,
    ProviderInvoker,
)
from .runner_sync_modes import get_sync_strategy, SyncRunContext
from .shadow import DEFAULT_METRICS_PATH
from .utils import content_hash, elapsed_ms


_CANCELLED_RESULT_WAIT_S = 0.05
_CANCELLED_RESULT_POLL_S = 0.001


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
        self._time_fn = time.time
        self._elapsed_ms = elapsed_ms
        self._provider_invoker = ProviderInvoker(
            rate_limiter=self._rate_limiter,
            run_with_shadow=_DEFAULT_RUN_WITH_SHADOW,
            log_provider_call=log_provider_call,
            log_provider_skipped=log_provider_skipped,
            time_fn=self._time_fn,
            elapsed_ms=self._elapsed_ms,
        )
        self._parallel_logger = ParallelResultLogger(
            log_provider_call=log_provider_call,
            log_run_metric=log_run_metric,
            estimate_cost=estimate_cost,
            elapsed_ms=self._elapsed_ms,
        )

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
        return self._provider_invoker.invoke(
            provider,
            request,
            attempt=attempt,
            total_providers=total_providers,
            event_logger=event_logger,
            request_fingerprint=request_fingerprint,
            metadata=metadata,
            shadow=shadow,
            metrics_path=metrics_path,
            capture_shadow_metrics=capture_shadow_metrics,
        )

    def _apply_cancelled_results(
        self,
        results: list[ProviderInvocationResult | None],
        *,
        providers: Sequence[ProviderSPI],
        cancelled_indices: Sequence[int],
        total_providers: int,
        run_started: float,
        started_indices: Collection[int] | None = None,
    ) -> None:
        if not cancelled_indices:
            return
        started = set(started_indices or ())
        pending = [
            index
            for index in cancelled_indices
            if 0 <= index < len(results)
            and index in started
            and results[index] is None
        ]
        if pending:
            deadline = self._time_fn() + _CANCELLED_RESULT_WAIT_S
            while pending and self._time_fn() < deadline:
                if all(results[index] is not None for index in pending):
                    break
                time.sleep(_CANCELLED_RESULT_POLL_S)
                pending = [
                    index for index in pending if results[index] is None
                ]
        builder = CancelledResultsBuilder(
            run_started=run_started,
            elapsed_ms=self._elapsed_ms,
        )
        builder.apply(
            results,
            providers=providers,
            cancelled_indices=cancelled_indices,
            total_providers=total_providers,
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
        self._parallel_logger.log_results(
            results,
            event_logger=event_logger,
            request=request,
            request_fingerprint=request_fingerprint,
            metadata=metadata,
            run_started=run_started,
            shadow_used=shadow_used,
            skip=skip,
            attempts_override=attempts_override,
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

        metrics_path = (
            self._config.metrics_path
            if shadow_metrics_path == DEFAULT_METRICS_PATH
            else shadow_metrics_path
        )
        event_logger, metrics_path_str = resolve_event_logger(
            self._logger, metrics_path
        )
        metadata = dict(request.metadata or {})
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )
        shadow_provider = shadow
        if shadow_provider is None:
            shadow_provider = getattr(self._config, "shadow_provider", None)
        shadow_used = shadow_provider is not None
        provider_names = [provider.name() for provider in self.providers]
        metadata.update(
            {
                "run_id": request_fingerprint,
                "mode": getattr(self._config.mode, "value", str(self._config.mode)),
                "providers": provider_names,
                "shadow_used": shadow_used,
                "shadow_provider_id": shadow_provider.name() if shadow_provider else None,
            }
        )
        strategy = get_sync_strategy(cast(RunnerMode, self._config.mode))
        context = SyncRunContext(
            runner=self,
            request=request,
            event_logger=event_logger,
            metadata=metadata,
            run_started=run_started,
            request_fingerprint=request_fingerprint,
            shadow=shadow_provider,
            shadow_used=shadow_used,
            metrics_path=metrics_path_str,
            run_parallel_all=run_parallel_all_sync,
            run_parallel_any=run_parallel_any_sync,
        )
        return strategy.execute(context)


__all__ = ["Runner", "ProviderInvocationResult"]
