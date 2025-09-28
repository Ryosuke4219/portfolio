"""Asynchronous runner implementation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import (
    FatalError,
    ProviderSkip,
    RateLimitError,
    RetryableError,
    SkipError,
    TimeoutError,
)
from .observability import EventLogger
from .provider_spi import (
    AsyncProviderSPI,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
    ensure_async_provider,
)
from .runner_config import RunnerConfig, RunnerMode
from .runner_shared import (
    MetricsPath,
    error_family,
    estimate_cost,
    log_provider_call,
    log_provider_skipped,
    log_run_metric,
    resolve_event_logger,
)
from .runner_parallel import (
    ParallelExecutionError,
    compute_consensus,
    run_parallel_all_async,
    run_parallel_any_async,
)
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow_async
from .utils import content_hash, elapsed_ms


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
    ) -> ProviderResponse:
        attempt_started = time.time()
        try:
            response = await run_with_shadow_async(
                async_provider,
                shadow_async,
                request,
                metrics_path=metrics_path,
                logger=event_logger,
            )
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
        log_provider_call(
            event_logger,
            request_fingerprint=request_fingerprint,
            provider=provider,
            request=request,
            attempt=attempt,
            total_providers=total_providers,
            status="ok",
            latency_ms=response.latency_ms,
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            error=None,
            metadata=metadata,
            shadow_used=shadow is not None,
            allow_private_model=True,
        )
        return response

    async def run_async(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | AsyncProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse:
        last_err: Exception | None = None
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

        mode = self._config.mode
        attempt_count = 0

        if mode is RunnerMode.SEQUENTIAL:
            for attempt_index, (provider, async_provider) in enumerate(providers, start=1):
                attempt_count = attempt_index
                try:
                    response = await self._invoke_provider_async(
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
                    )
                except RateLimitError as err:
                    last_err = err
                    sleep_duration = self._config.backoff.rate_limit_sleep_s
                    if sleep_duration > 0:
                        await asyncio.sleep(sleep_duration)
                    continue
                except RetryableError as err:
                    last_err = err
                    if isinstance(err, TimeoutError):
                        if self._config.backoff.timeout_next_provider:
                            continue
                        raise
                    if self._config.backoff.retryable_next_provider:
                        continue
                    raise
                except SkipError as err:
                    last_err = err
                    continue
                except FatalError as err:
                    last_err = err
                    raise
                else:
                    tokens_in = response.input_tokens
                    tokens_out = response.output_tokens
                    cost_usd = estimate_cost(provider, tokens_in, tokens_out)
                    log_run_metric(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        request=request,
                        provider=provider,
                        status="ok",
                        attempts=attempt_index,
                        latency_ms=elapsed_ms(run_started),
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_usd=cost_usd,
                        error=None,
                        metadata=metadata,
                        shadow_used=shadow is not None,
                    )
                    return response
        else:
            attempt_count = total_providers

            def _build_worker(
                provider: ProviderSPI | AsyncProviderSPI,
                async_provider: AsyncProviderSPI,
                attempt_index: int,
            ):
                async def _worker() -> tuple[int, ProviderSPI | AsyncProviderSPI, ProviderResponse]:
                    response = await self._invoke_provider_async(
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
                    )
                    return attempt_index, provider, response

                return _worker

            workers = [
                _build_worker(provider, async_provider, index)
                for index, (provider, async_provider) in enumerate(providers, start=1)
            ]

            try:
                if mode is RunnerMode.PARALLEL_ANY:
                    attempt_index, provider, response = await run_parallel_any_async(
                        workers,
                        max_concurrency=self._config.max_concurrency,
                    )
                    tokens_in = response.input_tokens
                    tokens_out = response.output_tokens
                    cost_usd = estimate_cost(provider, tokens_in, tokens_out)
                    log_run_metric(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        request=request,
                        provider=provider,
                        status="ok",
                        attempts=attempt_index,
                        latency_ms=elapsed_ms(run_started),
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_usd=cost_usd,
                        error=None,
                        metadata=metadata,
                        shadow_used=shadow is not None,
                    )
                    return response
                results = await run_parallel_all_async(
                    workers,
                    max_concurrency=self._config.max_concurrency,
                )
            except Exception as err:  # noqa: BLE001
                last_err = err
            else:
                if not results:
                    last_err = RuntimeError("No providers succeeded")
                else:
                    if mode is RunnerMode.CONSENSUS:
                        try:
                            consensus = compute_consensus(
                                [response for _, _, response in results],
                                config=self._config.consensus,
                            )
                        except ParallelExecutionError as err:
                            last_err = err
                        else:
                            for _attempt_index, provider, response in results:
                                if response is consensus.response:
                                    tokens_in = response.input_tokens
                                    tokens_out = response.output_tokens
                                    cost_usd = estimate_cost(provider, tokens_in, tokens_out)
                                    log_run_metric(
                                        event_logger,
                                        request_fingerprint=request_fingerprint,
                                        request=request,
                                        provider=provider,
                                        status="ok",
                                        attempts=attempt_count,
                                        latency_ms=elapsed_ms(run_started),
                                        tokens_in=tokens_in,
                                        tokens_out=tokens_out,
                                        cost_usd=cost_usd,
                                        error=None,
                                        metadata=metadata,
                                        shadow_used=shadow is not None,
                                    )
                                    return response
                            last_err = ParallelExecutionError("consensus resolution failed")
                    else:
                        _attempt_index, provider, response = results[0]
                        tokens_in = response.input_tokens
                        tokens_out = response.output_tokens
                        cost_usd = estimate_cost(provider, tokens_in, tokens_out)
                        log_run_metric(
                            event_logger,
                            request_fingerprint=request_fingerprint,
                            request=request,
                            provider=provider,
                            status="ok",
                            attempts=attempt_count,
                            latency_ms=elapsed_ms(run_started),
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            cost_usd=cost_usd,
                            error=None,
                            metadata=metadata,
                            shadow_used=shadow is not None,
                        )
                        return response

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
