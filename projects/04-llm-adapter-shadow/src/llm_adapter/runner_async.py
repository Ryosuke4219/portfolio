"""Asynchronous runner implementation."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import time
from typing import Any, cast

from ._event_loop import ensure_socket_free_event_loop_policy
from .errors import (
    FatalError,
    ProviderSkip,
    RateLimitError,
    RetryableError,
    SkipError,
)
from .observability import EventLogger
from .parallel_exec import ParallelAllResult, ParallelExecutionError
from .provider_spi import (
    AsyncProviderSPI,
    ensure_async_provider,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
)
from .runner_async_modes import (
    AsyncRunContext,
    collect_failure_details,
    ConsensusRunStrategy,
    ParallelAllRunStrategy,
    ParallelAnyRunStrategy,
    SequentialRunStrategy,
    WorkerResult,
)
from .runner_config import RunnerConfig, RunnerMode
from .runner_shared import (
    error_family,
    log_provider_call,
    log_provider_skipped,
    log_run_metric,
    MetricsPath,
    RateLimiter,
    resolve_event_logger,
    resolve_rate_limiter,
)
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow_async, ShadowMetrics
from .utils import content_hash, elapsed_ms

ensure_socket_free_event_loop_policy()


class AsyncRunner:
    """Async counterpart of :class:`Runner` providing ``asyncio`` bridges."""

    def __init__(
        self,
        providers: Sequence[ProviderSPI | AsyncProviderSPI],
        logger: EventLogger | None = None,
        *,
        config: RunnerConfig | None = None,
    ) -> None:
        if not providers:
            raise ValueError("AsyncRunner requires at least one provider")
        self.providers: list[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]] = [
            (provider, ensure_async_provider(provider)) for provider in providers
        ]
        self._logger = logger
        self._config = config or RunnerConfig()
        self._rate_limiter: RateLimiter | None = resolve_rate_limiter(self._config.rpm)

    async def _invoke_provider_async(
        self,
        provider: ProviderSPI | AsyncProviderSPI,
        async_provider: AsyncProviderSPI,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        event_logger: EventLogger | None,
        request_fingerprint: str,
        metadata: Mapping[str, Any],
        shadow: ProviderSPI | AsyncProviderSPI | None,
        shadow_async: AsyncProviderSPI | None,
        metrics_path: str | None,
        capture_shadow_metrics: bool,
    ) -> tuple[ProviderResponse, ShadowMetrics | None]:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire_async()
        attempt_started = time.time()
        shadow_metrics: ShadowMetrics | None = None
        response: ProviderResponse
        try:
            if capture_shadow_metrics:
                response_with_metrics = await run_with_shadow_async(
                    async_provider,
                    shadow_async,
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
                response_only = await run_with_shadow_async(
                    async_provider,
                    shadow_async,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=False,
                )
                response = cast(ProviderResponse, response_only)
        except RateLimitError as err:
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        except RetryableError as err:
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        except SkipError as err:
            if isinstance(err, ProviderSkip):
                log_provider_skipped(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt,
                    total_providers=total_providers,
                    error=err,
                )
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        except FatalError as err:
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        token_usage = response.token_usage
        log_provider_call(
            event_logger,
            request_fingerprint=request_fingerprint,
            provider=provider,
            request=request,
            attempt=attempt,
            total_providers=total_providers,
            status="ok",
            latency_ms=response.latency_ms,
            tokens_in=token_usage.prompt,
            tokens_out=token_usage.completion,
            error=None,
            metadata=metadata,
            shadow_used=shadow is not None,
            allow_private_model=True,
        )
        return response, shadow_metrics

    async def run_async(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | AsyncProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse | ParallelAllResult[WorkerResult, ProviderResponse]:
        event_logger, metrics_path_str = resolve_event_logger(
            self._logger, shadow_metrics_path
        )
        metadata = request.metadata or {}
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )

        shadow_async = ensure_async_provider(shadow) if shadow is not None else None

        max_attempts = self._config.max_attempts
        providers: Sequence[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]]
        if max_attempts is not None:
            providers = self.providers[: max(0, max_attempts)]
        else:
            providers = self.providers
        total_providers = len(providers)
        mode = RunnerMode(self._config.mode)

        async def _invoke(
            attempt_index: int,
            provider: ProviderSPI | AsyncProviderSPI,
            async_provider: AsyncProviderSPI,
            capture_shadow_metrics: bool,
        ) -> tuple[ProviderResponse, ShadowMetrics | None]:
            return await self._invoke_provider_async(
                provider,
                async_provider,
                request,
                attempt=attempt_index,
                total_providers=total_providers,
                event_logger=event_logger,
                request_fingerprint=request_fingerprint,
                metadata=metadata,
                shadow=shadow,
                shadow_async=shadow_async,
                metrics_path=metrics_path_str,
                capture_shadow_metrics=capture_shadow_metrics,
            )

        context = AsyncRunContext(
            request=request,
            providers=providers,
            event_logger=event_logger,
            metadata=metadata,
            request_fingerprint=request_fingerprint,
            run_started=run_started,
            shadow=shadow,
            shadow_async=shadow_async,
            metrics_path=metrics_path_str,
            config=self._config,
            mode=mode,
            invoke_provider=_invoke,
            sleep_fn=asyncio.sleep,
        )

        if mode == RunnerMode.SEQUENTIAL:
            strategy = SequentialRunStrategy()
        elif mode == RunnerMode.PARALLEL_ANY:
            strategy = ParallelAnyRunStrategy()
        elif mode == RunnerMode.PARALLEL_ALL:
            strategy = ParallelAllRunStrategy()
        elif mode == RunnerMode.CONSENSUS:
            strategy = ConsensusRunStrategy()
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported runner mode: {mode}")

        strategy_result = await strategy.run(context)

        if strategy_result.value is not None:
            return strategy_result.value

        attempt_count = strategy_result.attempt_count or context.attempt_count or total_providers
        last_err = strategy_result.last_error or context.last_error
        results = strategy_result.results
        failure_details = strategy_result.failure_details

        if mode == RunnerMode.CONSENSUS:
            if results is not None:
                for _, _, _, metrics in results:
                    if metrics is not None:
                        metrics.emit()
                no_success = not any(
                    len(entry) >= 3 and entry[2] is not None for entry in results
                )
                if no_success and not failure_details:
                    failure_details = collect_failure_details(context)
            elif not failure_details:
                failure_details = collect_failure_details(context)
            if failure_details and (
                last_err is None or not isinstance(last_err, ParallelExecutionError)
            ):
                detail_text = "; ".join(
                    f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
                    for item in failure_details
                )
                message = "all workers failed"
                if detail_text:
                    message = f"{message}: {detail_text}"
                last_err = ParallelExecutionError(message, failures=failure_details)

        if event_logger is not None:
            event_logger.emit(
                "provider_chain_failed",
                {
                    "request_fingerprint": request_fingerprint,
                    "provider_attempts": attempt_count,
                    "providers": [provider.name() for provider, _ in providers],
                    "last_error_type": type(last_err).__name__ if last_err else None,
                    "last_error_message": str(last_err) if last_err else None,
                    "last_error_family": error_family(last_err),
                },
            )
        log_run_metric(
            event_logger,
            request_fingerprint=request_fingerprint,
            request=request,
            provider=None,
            status="error",
            attempts=attempt_count,
            latency_ms=elapsed_ms(run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=last_err,
            metadata=metadata,
            shadow_used=shadow is not None,
        )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")


__all__ = ["AsyncRunner"]
