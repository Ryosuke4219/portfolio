"""Asynchronous runner implementation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, cast, overload

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
from .runner_parallel import (
    ConsensusFailure,
    ParallelAllResult,
    ParallelExecutionError,
    compute_consensus,
    run_parallel_all_async,
    run_parallel_any_async,
)
from .runner_shared import (
    MetricsPath,
    RateLimiter,
    error_family,
    estimate_cost,
    log_provider_call,
    log_provider_skipped,
    log_run_metric,
    resolve_event_logger,
    resolve_rate_limiter,
)
from .shadow import DEFAULT_METRICS_PATH, ShadowMetrics, run_with_shadow_async
from .utils import content_hash, elapsed_ms

WorkerSuccessResult = tuple[
    int,
    ProviderSPI | AsyncProviderSPI,
    ProviderResponse,
    ShadowMetrics | None,
    None,
]
WorkerFailureResult = tuple[
    int,
    ProviderSPI | AsyncProviderSPI,
    None,
    ShadowMetrics | None,
    Exception,
]
WorkerResult = WorkerSuccessResult | WorkerFailureResult
WorkerSuccessFactory = Callable[[], Awaitable[WorkerSuccessResult]]
WorkerFactory = Callable[[], Awaitable[WorkerResult]]


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
                    response, _ = await self._invoke_provider_async(
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
                        capture_shadow_metrics=False,
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
                    usage = response.token_usage
                    tokens_in = usage.prompt
                    tokens_out = usage.completion
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

            capture_shadow, retry_attempts = mode is RunnerMode.CONSENSUS, 0

            async def _handle_parallel_retry(
                worker_index: int, attempt_index: int, error: BaseException
            ) -> float | None:
                nonlocal retry_attempts, attempt_count
                provider, _ = providers[worker_index]
                next_attempt_total = total_providers + retry_attempts + 1
                delay: float | None = None
                if isinstance(error, RateLimitError):
                    delay = max(self._config.backoff.rate_limit_sleep_s, 0.0)
                elif isinstance(error, TimeoutError):
                    if not self._config.backoff.timeout_next_provider:
                        delay = 0.0
                elif isinstance(error, RetryableError):
                    if not self._config.backoff.retryable_next_provider:
                        delay = 0.0
                if delay is None or (
                    (limit := self._config.max_attempts) is not None
                    and next_attempt_total > limit
                ):
                    return None
                retry_attempts, attempt_count = retry_attempts + 1, next_attempt_total
                if event_logger is not None:
                    event_logger.emit(
                        "retry",
                        {
                            "request_fingerprint": request_fingerprint,
                            "provider": provider.name(),
                            "attempt": attempt_index,
                            "retry_attempt": retry_attempts,
                            "error_type": type(error).__name__,
                        },
                    )
                return delay
            @overload
            def _build_worker(
                provider: ProviderSPI | AsyncProviderSPI,
                async_provider: AsyncProviderSPI,
                attempt_index: int,
                *,
                allow_failures: Literal[True],
            ) -> WorkerFactory:
                ...

            @overload
            def _build_worker(
                provider: ProviderSPI | AsyncProviderSPI,
                async_provider: AsyncProviderSPI,
                attempt_index: int,
                *,
                allow_failures: Literal[False],
            ) -> WorkerSuccessFactory:
                ...

            def _build_worker(
                provider: ProviderSPI | AsyncProviderSPI,
                async_provider: AsyncProviderSPI,
                attempt_index: int,
                *,
                allow_failures: bool,
            ) -> WorkerFactory | WorkerSuccessFactory:
                if allow_failures:
                    async def _worker_with_failures() -> WorkerResult:
                        try:
                            response, shadow_metrics = await self._invoke_provider_async(
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
                                capture_shadow_metrics=capture_shadow,
                            )
                        except Exception as error:  # noqa: BLE001
                            return attempt_index, provider, None, None, error
                        return attempt_index, provider, response, shadow_metrics, None

                    return _worker_with_failures

                async def _worker_success() -> WorkerSuccessResult:
                    response, shadow_metrics = await self._invoke_provider_async(
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
                        capture_shadow_metrics=capture_shadow,
                    )
                    return attempt_index, provider, response, shadow_metrics, None

                return _worker_success

            enumerated_providers = list(enumerate(providers, start=1))

            consensus_results: list[WorkerResult] | None = None

            if mode is RunnerMode.PARALLEL_ANY:
                workers_any: list[WorkerSuccessFactory] = [
                    _build_worker(
                        provider,
                        async_provider,
                        index,
                        allow_failures=False,
                    )
                    for index, (provider, async_provider) in enumerated_providers
                ]
                try:
                    (
                        attempt_index,
                        provider,
                        response,
                        shadow_metrics,
                        error,
                    ) = await run_parallel_any_async(
                        workers_any,
                        max_concurrency=self._config.max_concurrency,
                        max_attempts=self._config.max_attempts,
                        on_retry=_handle_parallel_retry,
                    )
                except Exception as err:  # noqa: BLE001
                    last_err = err
                else:
                    if error is not None:
                        raise ParallelExecutionError("all workers failed") from error
                    usage = response.token_usage
                    tokens_in = usage.prompt
                    tokens_out = usage.completion
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
                    if shadow_metrics is not None:
                        shadow_metrics.emit()
                    return response
            elif mode is RunnerMode.CONSENSUS:
                workers_consensus: list[WorkerFactory] = [
                    _build_worker(
                        provider,
                        async_provider,
                        index,
                        allow_failures=True,
                    )
                    for index, (provider, async_provider) in enumerated_providers
                ]
                try:
                    consensus_results = await run_parallel_all_async(
                        workers_consensus,
                        max_concurrency=self._config.max_concurrency,
                    )
                except Exception as err:  # noqa: BLE001
                    last_err = err
                else:
                    if not consensus_results:
                        last_err = RuntimeError("No providers succeeded")
                    else:
                        try:
                            successful_entries = [
                                (attempt, provider, response, metrics)
                                for attempt, provider, response, metrics, error in consensus_results
                                if response is not None
                            ]
                            if not successful_entries:
                                raise ParallelExecutionError("all workers failed")
                            consensus_failures = [
                                ConsensusFailure(
                                    provider=provider.name(),
                                    attempt=attempt,
                                    error_type=type(error).__name__,
                                    error_message=str(error) if error is not None else None,
                                )
                                for attempt, provider, _response, _metrics, error in consensus_results
                                if error is not None
                            ]
                            consensus = compute_consensus(
                                [response for _, _, response, _ in successful_entries],
                                config=self._config.consensus,
                                failures=consensus_failures,
                            )
                        except ParallelExecutionError as err:
                            last_err = err
                        else:
                            winner_entry = next(
                                (
                                    attempt,
                                    provider,
                                    response,
                                    metrics,
                                )
                                for attempt, provider, response, metrics in successful_entries
                                if response is consensus.response
                            )
                            votes_against = (
                                consensus.total_voters
                                - consensus.votes
                                - consensus.abstained
                            )
                            if event_logger is not None:
                                candidate_summaries = [
                                    {
                                        "provider": provider.name(),
                                        "latency_ms": response.latency_ms,
                                        "votes": consensus.tally.get(
                                            response.text.strip(), 0
                                        ),
                                        "text_hash": content_hash(
                                            "consensus", response.text
                                        ),
                                    }
                                    for _, provider, response, _ in successful_entries
                                ]
                                failure_summaries = [
                                    {
                                        "provider": failure.provider,
                                        "attempt": failure.attempt,
                                        "error_type": failure.error_type,
                                        "error_message": failure.error_message,
                                    }
                                    for failure in consensus.failures
                                ]
                                event_logger.emit(
                                    "consensus_vote",
                                    {
                                        "request_fingerprint": request_fingerprint,
                                        "strategy": consensus.strategy,
                                        "tie_breaker": consensus.tie_breaker,
                                        "min_votes": consensus.min_votes,
                                        "score_threshold": consensus.score_threshold,
                                        "voters_total": consensus.total_voters,
                                        "votes_for": consensus.votes,
                                        "votes_against": votes_against,
                                        "abstained": consensus.abstained,
                                        "failures_total": len(consensus.failures),
                                        "winner_provider": winner_entry[1].name(),
                                        "winner_score": consensus.winner_score,
                                        "winner_latency_ms": consensus.response.latency_ms,
                                        "tie_break_applied": consensus.tie_break_applied,
                                        "tie_break_reason": consensus.tie_break_reason,
                                        "tie_breaker_selected": consensus.tie_breaker_selected,
                                        "rounds": consensus.rounds,
                                        "scores": consensus.scores,
                                        "schema_checked": consensus.schema_checked,
                                        "schema_failures": consensus.schema_failures,
                                        "judge": consensus.judge_name,
                                        "judge_score": consensus.judge_score,
                                        "votes": dict(consensus.tally),
                                        "candidate_summaries": candidate_summaries,
                                        "failures": failure_summaries,
                                    },
                                )
                            (
                                attempt_index,
                                provider,
                                response,
                                shadow_metrics,
                            ) = winner_entry
                            usage = response.token_usage
                            tokens_in = usage.prompt
                            tokens_out = usage.completion
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
                            if shadow_metrics is not None:
                                shadow_payload = shadow_metrics.payload
                                extra: dict[str, object] = {
                                    "shadow_consensus_delta": {
                                        "votes_for": consensus.votes,
                                        "votes_total": consensus.total_voters,
                                        "tie_break_applied": consensus.tie_break_applied,
                                        "winner_score": consensus.winner_score,
                                        "rounds": consensus.rounds,
                                        "tie_break_reason": consensus.tie_break_reason,
                                        "tie_breaker_selected": consensus.tie_breaker_selected,
                                        "judge": consensus.judge_name,
                                        "judge_score": consensus.judge_score,
                                        "failures_total": len(consensus.failures),
                                    }
                                }
                                if not shadow_payload.get("shadow_ok", True):
                                    error = shadow_payload.get("shadow_error")
                                    if error is not None:
                                        extra["shadow_consensus_error"] = error
                                shadow_metrics.emit(extra)
                            for _, _, _, metrics in successful_entries:
                                if metrics is not None and metrics is not shadow_metrics:
                                    metrics.emit()
                            return response
            else:
                workers_all: list[WorkerSuccessFactory] = [
                    _build_worker(
                        provider,
                        async_provider,
                        index,
                        allow_failures=False,
                    )
                    for index, (provider, async_provider) in enumerated_providers
                ]
                try:
                    results_success: list[WorkerSuccessResult] = await run_parallel_all_async(
                        workers_all,
                        max_concurrency=self._config.max_concurrency,
                    )
                except Exception as err:  # noqa: BLE001
                    last_err = err
                else:
                    if not results_success:
                        last_err = RuntimeError("No providers succeeded")
                    else:
                        _attempt_index, provider, response, _metrics, _error = results_success[0]
                        usage = response.token_usage
                        tokens_in = usage.prompt
                        tokens_out = usage.completion
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
                        def _primary_response(entry: WorkerSuccessResult) -> ProviderResponse:
                            return entry[2]

                        result = ParallelAllResult[WorkerSuccessResult, ProviderResponse](
                            results_success,
                            _primary_response,
                        )
                        return cast(
                            ParallelAllResult[WorkerResult, ProviderResponse],
                            result,
                        )

        if mode is RunnerMode.CONSENSUS and consensus_results is not None:
            for entry in consensus_results:
                entry_response: ProviderResponse | None = entry[2]
                metrics = entry[3]
                if metrics is not None and entry_response is not None:
                    metrics.emit()

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
