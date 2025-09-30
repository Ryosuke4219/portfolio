"""Run providers in parallel until any succeed."""
from __future__ import annotations

from ..parallel_exec import run_parallel_any_async
from ..runner_shared import estimate_cost, log_run_metric
from ..utils import elapsed_ms
from .base import ParallelStrategyBase
from .context import AsyncRunContext, StrategyResult


class ParallelAnyRunStrategy(ParallelStrategyBase):
    def __init__(self) -> None:
        super().__init__(capture_shadow_metrics=False, is_parallel_any=True)

    async def run(self, context: AsyncRunContext) -> StrategyResult:
        self._reset_context(context)
        workers = self._create_workers(context)
        try:
            attempt_index, provider, response, shadow_metrics = await run_parallel_any_async(
                workers,
                max_concurrency=context.config.max_concurrency,
                max_attempts=context.config.max_attempts,
                on_retry=lambda index, attempt, error: self._on_retry(
                    context, index, attempt, error
                ),
            )
        except Exception as err:  # noqa: BLE001
            context.last_error = err
            return StrategyResult(None, context.attempt_count, context.last_error)

        usage = response.token_usage
        tokens_in = usage.prompt
        tokens_out = usage.completion
        cost_usd = estimate_cost(provider, tokens_in, tokens_out)
        log_run_metric(
            context.event_logger,
            request_fingerprint=context.request_fingerprint,
            request=context.request,
            provider=provider,
            status="ok",
            attempts=attempt_index,
            latency_ms=elapsed_ms(context.run_started),
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
