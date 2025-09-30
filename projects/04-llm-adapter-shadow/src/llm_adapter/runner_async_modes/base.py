"""Base helpers for async runner strategies."""
from __future__ import annotations


from ..errors import RateLimitError, RetryableError, TimeoutError
from ..provider_spi import AsyncProviderSPI, ProviderSPI
from .context import AsyncRunContext, WorkerFactory, WorkerResult

__all__ = ["ParallelStrategyBase", "compute_parallel_retry_decision"]


RetryDecision = tuple[int, float]


def compute_parallel_retry_decision(
    *,
    error: BaseException,
    is_parallel_any: bool,
    context: AsyncRunContext,
) -> RetryDecision | None:
    next_attempt_total = context.total_providers + context.retry_attempts + 1
    delay: float | None = None
    if isinstance(error, RateLimitError):
        delay = context.config.backoff.rate_limit_sleep_s
    elif isinstance(error, TimeoutError):
        if not context.config.backoff.timeout_next_provider:
            delay = 0.0
    elif isinstance(error, RetryableError):
        if not context.config.backoff.retryable_next_provider:
            delay = 0.0
    elif is_parallel_any:
        return None
    if delay is None:
        return None
    delay = max(0.0, float(delay))
    limit = context.config.max_attempts
    if limit is not None and next_attempt_total > limit:
        return None
    return next_attempt_total, delay


class ParallelStrategyBase:
    def __init__(self, *, capture_shadow_metrics: bool, is_parallel_any: bool) -> None:
        self._capture_shadow_metrics = capture_shadow_metrics
        self._is_parallel_any = is_parallel_any

    def _reset_context(self, context: AsyncRunContext) -> None:
        total = context.total_providers
        context.attempt_count = total
        context.retry_attempts = 0
        context.results = None
        context.last_error = None
        context.failure_records = [None] * total
        context.attempted = [False] * total
        context.attempt_labels = [index for index in range(1, total + 1)]
        context.pending_retry_events.clear()

    def _build_worker(
        self,
        context: AsyncRunContext,
        worker_index: int,
        provider: ProviderSPI | AsyncProviderSPI,
        async_provider: AsyncProviderSPI,
    ) -> WorkerFactory:
        async def _worker() -> WorkerResult:
            attempt_index = context.attempt_labels[worker_index]
            if context.event_logger is not None:
                pending_payload = context.pending_retry_events.pop(worker_index, None)
                if (
                    pending_payload is not None
                    and pending_payload.get("next_attempt") == attempt_index
                ):
                    context.event_logger.emit("retry", pending_payload)
                elif pending_payload is not None:
                    context.pending_retry_events[worker_index] = pending_payload
            context.attempted[worker_index] = True
            try:
                response, shadow_metrics = await context.invoke_provider(
                    attempt_index,
                    provider,
                    async_provider,
                    self._capture_shadow_metrics,
                )
            except Exception as exc:  # noqa: BLE001
                context.failure_records[worker_index] = {
                    "provider": provider.name(),
                    "attempt": str(attempt_index),
                    "summary": f"{type(exc).__name__}: {exc}",
                }
                raise
            context.failure_records[worker_index] = None
            return attempt_index, provider, response, shadow_metrics

        return _worker

    async def _on_retry(
        self,
        context: AsyncRunContext,
        worker_index: int,
        attempt_index: int,
        error: BaseException,
    ) -> RetryDecision | None:
        decision = compute_parallel_retry_decision(
            error=error,
            is_parallel_any=self._is_parallel_any,
            context=context,
        )
        if decision is None:
            return None
        next_attempt_total, delay = decision
        retry_attempt = context.retry_attempts + 1
        context.retry_attempts = retry_attempt
        context.attempt_count = next_attempt_total
        context.attempt_labels[worker_index] = next_attempt_total
        if context.event_logger is not None:
            provider, _ = context.providers[worker_index]
            context.pending_retry_events[worker_index] = {
                "request_fingerprint": context.request_fingerprint,
                "provider": provider.name(),
                "attempt": attempt_index,
                "retry_attempt": retry_attempt,
                "next_attempt": next_attempt_total,
                "error_type": type(error).__name__,
                "delay_seconds": delay,
            }
        return next_attempt_total, delay

    def _create_workers(self, context: AsyncRunContext) -> list[WorkerFactory]:
        return [
            self._build_worker(context, index, provider, async_provider)
            for index, (provider, async_provider) in enumerate(context.providers)
        ]
