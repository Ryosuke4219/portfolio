"""Run all providers in parallel and aggregate responses."""
from __future__ import annotations

from ..parallel_exec import ParallelAllResult, run_parallel_all_async
from ..runner_shared import estimate_cost, log_run_metric
from .base import ParallelStrategyBase
from .context import AsyncRunContext, collect_failure_details, StrategyResult


class ParallelAllRunStrategy(ParallelStrategyBase):
    def __init__(self) -> None:
        super().__init__(capture_shadow_metrics=False, is_parallel_any=False)

    async def run(self, context: AsyncRunContext) -> StrategyResult:
        self._reset_context(context)
        workers = self._create_workers(context)
        try:
            results = await run_parallel_all_async(
                workers,
                max_concurrency=context.config.max_concurrency,
                max_attempts=context.config.max_attempts,
                on_retry=lambda index, attempt, error: self._on_retry(
                    context, index, attempt, error
                ),
            )
        except Exception as err:  # noqa: BLE001
            context.last_error = err
            failure_details = collect_failure_details(context)
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                failure_details=failure_details or None,
            )
        if not results:
            context.last_error = RuntimeError("No providers succeeded")
            return StrategyResult(None, context.attempt_count, context.last_error)

        context.results = results
        for attempt_index, provider, response, _metrics in results:
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
                latency_ms=response.latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                error=None,
                metadata=context.metadata,
                shadow_used=context.shadow is not None,
            )
        return StrategyResult(
            ParallelAllResult(results, lambda entry: entry[2]),
            context.attempt_count,
            None,
            results=results,
        )
