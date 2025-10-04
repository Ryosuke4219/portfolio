"""Run providers in parallel until any succeed."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast

from ..parallel_exec import ParallelExecutionError, run_parallel_any_async
from ..runner_shared import estimate_cost, log_provider_call, log_run_metric
from ..utils import elapsed_ms
from .base import ParallelStrategyBase
from .context import AsyncRunContext, collect_failure_details, StrategyResult


class ParallelAnyRunStrategy(ParallelStrategyBase):
    def __init__(self) -> None:
        super().__init__(capture_shadow_metrics=False, is_parallel_any=True)

    async def run(self, context: AsyncRunContext) -> StrategyResult:
        self._reset_context(context)
        workers = self._create_workers(context)
        cancelled_workers: tuple[int, ...] = ()

        def _record_cancelled(indices: Sequence[int]) -> None:
            nonlocal cancelled_workers
            cancelled_workers = tuple(indices)

        try:
            attempt_index, provider, response, shadow_metrics = await run_parallel_any_async(
                workers,
                max_concurrency=context.config.max_concurrency,
                max_attempts=context.config.max_attempts,
                on_retry=lambda index, attempt, error: self._on_retry(
                    context, index, attempt, error
                ),
                on_cancelled=_record_cancelled,
            )
        except Exception as err:  # noqa: BLE001
            context.last_error = err
            failure_details: list[dict[str, str]] | None = None
            if isinstance(err, ParallelExecutionError):
                failure_details = collect_failure_details(context) or None
                err.failures = failure_details
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                failure_details=failure_details,
            )

        if cancelled_workers:
            self._emit_cancelled_metrics(context, cancelled_workers)
        usage = response.token_usage
        tokens_in = usage.prompt
        tokens_out = usage.completion
        cost_usd = estimate_cost(provider, tokens_in, tokens_out)
        response_latency = getattr(response, "latency_ms", None)
        latency_ms = (
            int(response_latency)
            if response_latency is not None
            else elapsed_ms(context.run_started)
        )
        log_run_metric(
            context.event_logger,
            request_fingerprint=context.request_fingerprint,
            request=context.request,
            provider=provider,
            status="ok",
            attempts=attempt_index,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            error=None,
            metadata=context.metadata,
            shadow_used=context.shadow is not None,
        )
        if shadow_metrics is not None:
            shadow_metrics.emit()
        return StrategyResult(response, attempt_index, None)

    def _emit_cancelled_metrics(
        self, context: AsyncRunContext, cancelled_workers: Sequence[int]
    ) -> None:
        event_logger = context.event_logger
        metadata = context.metadata
        latency_ms = elapsed_ms(context.run_started)
        shadow_used = context.shadow is not None
        for index in cancelled_workers:
            if index < 0 or index >= context.total_providers:
                continue
            attempt_index = context.attempt_labels[index]
            provider, _ = context.providers[index]
            error = cast(Exception, asyncio.CancelledError())
            log_provider_call(
                event_logger,
                request_fingerprint=context.request_fingerprint,
                provider=provider,
                request=context.request,
                attempt=attempt_index,
                total_providers=context.total_providers,
                status="error",
                latency_ms=latency_ms,
                tokens_in=None,
                tokens_out=None,
                error=error,
                metadata=metadata,
                shadow_used=shadow_used,
                allow_private_model=True,
            )
            log_run_metric(
                event_logger,
                request_fingerprint=context.request_fingerprint,
                request=context.request,
                provider=provider,
                status="error",
                attempts=attempt_index,
                latency_ms=latency_ms,
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=error,
                metadata=metadata,
                shadow_used=shadow_used,
            )
