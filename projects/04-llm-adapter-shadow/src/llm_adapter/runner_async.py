"""Asynchronous runner implementation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence

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
    log_consensus_result,
    log_parallel_group_result,
    log_provider_call,
    log_provider_skipped,
    log_provider_chain_failed,
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

        mode = self._config.mode
        if mode is not RunnerMode.SEQUENTIAL:
            return await self._run_parallel(
                mode,
                request,
                shadow,
                shadow_async,
                shadow_metrics_path=metrics_path_str,
                event_logger=event_logger,
                metadata=metadata,
                run_started=run_started,
                request_fingerprint=request_fingerprint,
            )

        max_attempts = self._config.max_attempts
        attempt_count = 0
        for loop_index, (provider, async_provider) in enumerate(self.providers, start=1):
            if max_attempts is not None and loop_index > max_attempts:
                break
            attempt_index = loop_index
            attempt_count = attempt_index
            attempt_started = time.time()
            try:
                response = await run_with_shadow_async(
                    async_provider,
                    shadow_async,
                    request,
                    metrics_path=metrics_path_str,
                    logger=event_logger,
                )
            except RateLimitError as err:
                last_err = err
                log_provider_call(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt_index,
                    total_providers=len(self.providers),
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    metadata=metadata,
                    shadow_used=shadow is not None,
                    allow_private_model=True,
                )
                sleep_duration = self._config.backoff.rate_limit_sleep_s
                if sleep_duration > 0:
                    await asyncio.sleep(sleep_duration)
            except RetryableError as err:
                last_err = err
                log_provider_call(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt_index,
                    total_providers=len(self.providers),
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    metadata=metadata,
                    shadow_used=shadow is not None,
                    allow_private_model=True,
                )
                if isinstance(err, TimeoutError):
                    if self._config.backoff.timeout_next_provider:
                        continue
                    raise
                if self._config.backoff.retryable_next_provider:
                    continue
                raise
            except SkipError as err:
                last_err = err
                if isinstance(err, ProviderSkip):
                    log_provider_skipped(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        provider=provider,
                        request=request,
                        attempt=attempt_index,
                        total_providers=len(self.providers),
                        error=err,
                    )
                log_provider_call(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt_index,
                    total_providers=len(self.providers),
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    metadata=metadata,
                    shadow_used=shadow is not None,
                    allow_private_model=True,
                )
                continue
            except FatalError as err:
                last_err = err
                log_provider_call(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt_index,
                    total_providers=len(self.providers),
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
            else:
                log_provider_call(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt_index,
                    total_providers=len(self.providers),
                    status="ok",
                    latency_ms=response.latency_ms,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=None,
                    metadata=metadata,
                    shadow_used=shadow is not None,
                    allow_private_model=True,
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

        log_provider_chain_failed(
            event_logger,
            request_fingerprint=request_fingerprint,
            providers=[provider for provider, _ in self.providers],
            attempt_count=attempt_count,
            last_error=last_err,
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

    async def _run_parallel(
        self,
        mode: RunnerMode,
        request: ProviderRequest,
        shadow: ProviderSPI | AsyncProviderSPI | None,
        shadow_async: AsyncProviderSPI | None,
        *,
        shadow_metrics_path: str | None,
        event_logger: EventLogger | None,
        metadata: Mapping[str, object],
        run_started: float,
        request_fingerprint: str,
    ) -> ProviderResponse:
        providers = self._selected_providers()
        provider_objects = [provider for provider, _ in providers]
        shadow_used = shadow is not None
        if not providers:
            log_provider_chain_failed(
                event_logger,
                request_fingerprint=request_fingerprint,
                providers=provider_objects,
                attempt_count=0,
                last_error=None,
            )
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=None,
                status="error",
                attempts=0,
                latency_ms=elapsed_ms(run_started),
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=None,
                metadata=metadata,
                shadow_used=shadow_used,
            )
            raise RuntimeError("No providers succeeded")

        max_concurrency = self._config.max_concurrency
        attempts = len(providers)
        record_lock = asyncio.Lock()
        records: list[dict[str, object]] = []

        async def record_attempt(
            provider: ProviderSPI | AsyncProviderSPI,
            *,
            status: str,
            latency_ms: int | None,
            error: Exception | None,
            tokens_in: int | None,
            tokens_out: int | None,
        ) -> None:
            provider_name = provider.name() if hasattr(provider, "name") else None
            async with record_lock:
                records.append(
                    {
                        "provider": provider_name,
                        "status": status,
                        "latency_ms": latency_ms,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "error_type": type(error).__name__ if error else None,
                        "error_message": str(error) if error else None,
                        "error_family": error_family(error),
                    }
                )

        def make_worker(
            provider: ProviderSPI | AsyncProviderSPI,
            async_provider: AsyncProviderSPI,
            attempt_index: int,
        ):
            async def worker() -> ProviderResponse:
                attempt_started = time.time()
                try:
                    response = await run_with_shadow_async(
                        async_provider,
                        shadow_async,
                        request,
                        metrics_path=shadow_metrics_path,
                        logger=event_logger,
                    )
                except RateLimitError as err:
                    latency = elapsed_ms(attempt_started)
                    log_provider_call(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        provider=provider,
                        request=request,
                        attempt=attempt_index,
                        total_providers=attempts,
                        status="error",
                        latency_ms=latency,
                        tokens_in=None,
                        tokens_out=None,
                        error=err,
                        metadata=metadata,
                        shadow_used=shadow_used,
                        allow_private_model=True,
                    )
                    await record_attempt(
                        provider,
                        status="error",
                        latency_ms=latency,
                        error=err,
                        tokens_in=None,
                        tokens_out=None,
                    )
                    raise
                except RetryableError as err:
                    latency = elapsed_ms(attempt_started)
                    log_provider_call(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        provider=provider,
                        request=request,
                        attempt=attempt_index,
                        total_providers=attempts,
                        status="error",
                        latency_ms=latency,
                        tokens_in=None,
                        tokens_out=None,
                        error=err,
                        metadata=metadata,
                        shadow_used=shadow_used,
                        allow_private_model=True,
                    )
                    await record_attempt(
                        provider,
                        status="error",
                        latency_ms=latency,
                        error=err,
                        tokens_in=None,
                        tokens_out=None,
                    )
                    raise
                except SkipError as err:
                    latency = elapsed_ms(attempt_started)
                    if isinstance(err, ProviderSkip):
                        log_provider_skipped(
                            event_logger,
                            request_fingerprint=request_fingerprint,
                            provider=provider,
                            request=request,
                            attempt=attempt_index,
                            total_providers=attempts,
                            error=err,
                        )
                    log_provider_call(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        provider=provider,
                        request=request,
                        attempt=attempt_index,
                        total_providers=attempts,
                        status="error",
                        latency_ms=latency,
                        tokens_in=None,
                        tokens_out=None,
                        error=err,
                        metadata=metadata,
                        shadow_used=shadow_used,
                        allow_private_model=True,
                    )
                    await record_attempt(
                        provider,
                        status="error",
                        latency_ms=latency,
                        error=err,
                        tokens_in=None,
                        tokens_out=None,
                    )
                    raise
                except FatalError as err:
                    latency = elapsed_ms(attempt_started)
                    log_provider_call(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        provider=provider,
                        request=request,
                        attempt=attempt_index,
                        total_providers=attempts,
                        status="error",
                        latency_ms=latency,
                        tokens_in=None,
                        tokens_out=None,
                        error=err,
                        metadata=metadata,
                        shadow_used=shadow_used,
                        allow_private_model=True,
                    )
                    await record_attempt(
                        provider,
                        status="error",
                        latency_ms=latency,
                        error=err,
                        tokens_in=None,
                        tokens_out=None,
                    )
                    raise
                else:
                    log_provider_call(
                        event_logger,
                        request_fingerprint=request_fingerprint,
                        provider=provider,
                        request=request,
                        attempt=attempt_index,
                        total_providers=attempts,
                        status="ok",
                        latency_ms=response.latency_ms,
                        tokens_in=response.input_tokens,
                        tokens_out=response.output_tokens,
                        error=None,
                        metadata=metadata,
                        shadow_used=shadow_used,
                        allow_private_model=True,
                    )
                    await record_attempt(
                        provider,
                        status="ok",
                        latency_ms=response.latency_ms,
                        error=None,
                        tokens_in=response.input_tokens,
                        tokens_out=response.output_tokens,
                    )
                    return response

            return worker

        if mode is RunnerMode.PARALLEL_ANY:
            winner_provider: ProviderSPI | AsyncProviderSPI | None = None

            def make_any_worker(
                provider: ProviderSPI | AsyncProviderSPI,
                async_provider: AsyncProviderSPI,
                attempt_index: int,
            ):
                worker = make_worker(provider, async_provider, attempt_index)

                async def wrapped() -> ProviderResponse:
                    nonlocal winner_provider
                    response = await worker()
                    winner_provider = provider
                    return response

                return wrapped

            workers = [
                make_any_worker(provider, async_provider, idx + 1)
                for idx, (provider, async_provider) in enumerate(providers)
            ]
            try:
                response = await run_parallel_any_async(
                    workers, max_concurrency=max_concurrency
                )
            except ParallelExecutionError as err:
                last_error = err.__cause__ if err.__cause__ is not None else err
                log_parallel_group_result(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    mode=mode.value,
                    status="error",
                    attempts=attempts,
                    latency_ms=elapsed_ms(run_started),
                    records=records,
                    winner=None,
                    error=last_error,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                log_provider_chain_failed(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    providers=provider_objects,
                    attempt_count=attempts,
                    last_error=last_error,
                )
                log_run_metric(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    provider=None,
                    status="error",
                    attempts=attempts,
                    latency_ms=elapsed_ms(run_started),
                    tokens_in=None,
                    tokens_out=None,
                    cost_usd=0.0,
                    error=last_error,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                raise last_error
            else:
                if winner_provider is None:
                    winner_provider = provider_objects[0]
                tokens_in = response.input_tokens
                tokens_out = response.output_tokens
                cost_usd = estimate_cost(winner_provider, tokens_in, tokens_out)
                log_parallel_group_result(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    mode=mode.value,
                    status="ok",
                    attempts=attempts,
                    latency_ms=elapsed_ms(run_started),
                    records=records,
                    winner=winner_provider,
                    error=None,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                log_run_metric(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    provider=winner_provider,
                    status="ok",
                    attempts=attempts,
                    latency_ms=elapsed_ms(run_started),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    error=None,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                return response

        workers = [
            make_worker(provider, async_provider, idx + 1)
            for idx, (provider, async_provider) in enumerate(providers)
        ]
        try:
            responses = await run_parallel_all_async(
                workers, max_concurrency=max_concurrency
            )
        except BaseException as exc:
            log_parallel_group_result(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                mode=mode.value,
                status="error",
                attempts=attempts,
                latency_ms=elapsed_ms(run_started),
                records=records,
                winner=None,
                error=exc,
                metadata=metadata,
                shadow_used=shadow_used,
            )
            log_provider_chain_failed(
                event_logger,
                request_fingerprint=request_fingerprint,
                providers=provider_objects,
                attempt_count=attempts,
                last_error=exc,
            )
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=None,
                status="error",
                attempts=attempts,
                latency_ms=elapsed_ms(run_started),
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=exc,
                metadata=metadata,
                shadow_used=shadow_used,
            )
            raise

        if mode is RunnerMode.CONSENSUS:
            try:
                consensus = compute_consensus(
                    responses, config=self._config.consensus
                )
            except ParallelExecutionError as err:
                last_error = err.__cause__ if err.__cause__ is not None else err
                log_parallel_group_result(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    mode=mode.value,
                    status="error",
                    attempts=attempts,
                    latency_ms=elapsed_ms(run_started),
                    records=records,
                    winner=None,
                    error=last_error,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                log_consensus_result(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    mode=mode.value,
                    status="error",
                    votes=None,
                    total_candidates=len(responses),
                    winner=None,
                    error=last_error,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                log_run_metric(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    provider=None,
                    status="error",
                    attempts=attempts,
                    latency_ms=elapsed_ms(run_started),
                    tokens_in=None,
                    tokens_out=None,
                    cost_usd=0.0,
                    error=last_error,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                raise last_error
            winner_provider = next(
                (
                    provider
                    for provider, response in zip(provider_objects, responses)
                    if response is consensus.response
                ),
                None,
            )
            log_parallel_group_result(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                mode=mode.value,
                status="ok",
                attempts=attempts,
                latency_ms=elapsed_ms(run_started),
                records=records,
                winner=winner_provider,
                error=None,
                metadata=metadata,
                shadow_used=shadow_used,
            )
            log_consensus_result(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                mode=mode.value,
                status="ok",
                votes=consensus.votes,
                total_candidates=len(responses),
                winner=winner_provider,
                error=None,
                metadata=metadata,
                shadow_used=shadow_used,
            )
            tokens_in = consensus.response.input_tokens
            tokens_out = consensus.response.output_tokens
            cost_usd = estimate_cost(winner_provider, tokens_in, tokens_out)
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=winner_provider,
                status="ok",
                attempts=attempts,
                latency_ms=elapsed_ms(run_started),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                error=None,
                metadata=metadata,
                shadow_used=shadow_used,
            )
            return consensus.response

        tokens_in_total = sum((response.input_tokens or 0) for response in responses)
        tokens_out_total = sum((response.output_tokens or 0) for response in responses)
        cost_usd = sum(
            estimate_cost(
                provider,
                response.input_tokens or 0,
                response.output_tokens or 0,
            )
            for provider, response in zip(provider_objects, responses)
        )
        log_parallel_group_result(
            event_logger,
            request_fingerprint=request_fingerprint,
            request=request,
            mode=mode.value,
            status="ok",
            attempts=attempts,
            latency_ms=elapsed_ms(run_started),
            records=records,
            winner=None,
            error=None,
            metadata=metadata,
            shadow_used=shadow_used,
        )
        log_run_metric(
            event_logger,
            request_fingerprint=request_fingerprint,
            request=request,
            provider=None,
            status="ok",
            attempts=attempts,
            latency_ms=elapsed_ms(run_started),
            tokens_in=tokens_in_total,
            tokens_out=tokens_out_total,
            cost_usd=cost_usd,
            error=None,
            metadata=metadata,
            shadow_used=shadow_used,
        )
        return responses[0]

    def _selected_providers(
        self,
    ) -> list[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]]:
        max_attempts = self._config.max_attempts
        if max_attempts is None:
            return list(self.providers)
        if max_attempts <= 0:
            return []
        return list(self.providers[:max_attempts])


__all__ = ["AsyncRunner"]
