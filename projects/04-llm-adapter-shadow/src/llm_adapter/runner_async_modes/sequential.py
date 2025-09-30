"""Sequential run strategy."""
from __future__ import annotations

from ..errors import FatalError, RateLimitError, RetryableError, SkipError, TimeoutError
from ..runner_shared import estimate_cost, log_run_metric
from ..utils import elapsed_ms
from .context import AsyncRunContext, StrategyResult


class SequentialRunStrategy:
    async def run(self, context: AsyncRunContext) -> StrategyResult:
        for attempt_index, (provider, async_provider) in enumerate(context.providers, start=1):
            context.attempt_count = attempt_index
            try:
                response, _ = await context.invoke_provider(
                    attempt_index,
                    provider,
                    async_provider,
                    False,
                )
            except RateLimitError as err:
                context.last_error = err
                sleep_duration = context.config.backoff.rate_limit_sleep_s
                if sleep_duration > 0:
                    await context.sleep_fn(sleep_duration)
                continue
            except RetryableError as err:
                context.last_error = err
                if isinstance(err, TimeoutError):
                    if context.config.backoff.timeout_next_provider:
                        continue
                    raise
                if context.config.backoff.retryable_next_provider:
                    continue
                raise
            except SkipError as err:
                context.last_error = err
                continue
            except FatalError as err:
                context.last_error = err
                raise
            else:
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
                return StrategyResult(response, attempt_index, None)
        return StrategyResult(None, context.attempt_count, context.last_error)
