"""Asynchronous runner implementation."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
import time
from typing import Any

from ._event_loop import ensure_socket_free_event_loop_policy
from .errors import FatalError
from .observability import EventLogger
from .parallel_exec import ParallelAllResult
from .provider_spi import (
    AsyncProviderSPI,
    ensure_async_provider,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
)
from .runner_async_modes import (
    AsyncRunContext,
    AsyncRunStrategy,
    ConsensusRunStrategy,
    ParallelAllRunStrategy,
    ParallelAnyRunStrategy,
    SequentialRunStrategy,
    WorkerResult,
)
from .runner_async_support import AsyncProviderInvoker, emit_consensus_failure
from .runner_config import RunnerConfig, RunnerMode
from .runner_shared import (
    error_family,
    log_run_metric,
    MetricsPath,
    RateLimiter,
    resolve_event_logger,
    resolve_rate_limiter,
)
from .shadow import DEFAULT_METRICS_PATH, ShadowMetrics
from .utils import content_hash, elapsed_ms

ensure_socket_free_event_loop_policy()


class AllFailedError(FatalError):
    """Raised when all providers fail to produce a response."""


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
        self._invoker = AsyncProviderInvoker(rate_limiter=self._rate_limiter)

    async def run_async(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | AsyncProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse | ParallelAllResult[WorkerResult, ProviderResponse]:
        metrics_path = (
            self._config.metrics_path
            if shadow_metrics_path == DEFAULT_METRICS_PATH
            else shadow_metrics_path
        )
        event_logger, metrics_path_str = resolve_event_logger(
            self._logger, metrics_path
        )
        metadata: dict[str, Any] = dict(request.metadata or {})
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )

        shadow = shadow or getattr(self._config, "shadow_provider", None)
        shadow_async = ensure_async_provider(shadow) if shadow is not None else None

        max_attempts = self._config.max_attempts
        providers: Sequence[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]]
        if max_attempts is not None:
            providers = self.providers[: max(0, max_attempts)]
        else:
            providers = self.providers
        total_providers = len(providers)
        mode = RunnerMode(self._config.mode)
        metadata.setdefault("run_id", metadata.get("trace_id") or request_fingerprint)
        metadata["mode"] = mode.value
        metadata["providers"] = [provider.name() for provider, _ in providers]

        async def _invoke(
            attempt_index: int,
            provider: ProviderSPI | AsyncProviderSPI,
            async_provider: AsyncProviderSPI,
            capture_shadow_metrics: bool,
        ) -> tuple[ProviderResponse, ShadowMetrics | None]:
            return await self._invoker.invoke(
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

        strategy: AsyncRunStrategy
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
            failure_details, last_err = emit_consensus_failure(
                context=context,
                results=results,
                failure_details=failure_details,
                last_error=last_err,
            )

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
        failure_error = AllFailedError("All providers failed to produce a result")
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
            error=failure_error,
            metadata=metadata,
            shadow_used=shadow is not None,
        )
        if last_err is not None:
            if mode == RunnerMode.CONSENSUS or total_providers <= 1:
                raise last_err
            raise failure_error from last_err
        raise failure_error


__all__ = ["AllFailedError", "AsyncRunner"]
