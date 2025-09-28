"""Synchronous runner implementation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from .errors import (
    FatalError,
    ProviderSkip,
    RateLimitError,
    RetryableError,
    SkipError,
    TimeoutError,
)
from .observability import EventLogger
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerConfig, RunnerMode
from .runner_parallel import (
    ParallelAllResult,
    ParallelExecutionError,
    compute_consensus,
    run_parallel_all_sync,
    run_parallel_any_sync,
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
from .shadow import DEFAULT_METRICS_PATH, ShadowMetrics, run_with_shadow
from .utils import content_hash, elapsed_ms


@dataclass(slots=True)
class ProviderInvocationResult:
    provider: ProviderSPI
    attempt: int
    total_providers: int
    response: ProviderResponse | None
    error: Exception | None
    latency_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    shadow_metrics: ShadowMetrics | None
    shadow_metrics_extra: dict[str, object] | None


class Runner:
    """Attempt providers sequentially until one succeeds."""

    def __init__(
        self,
        providers: Sequence[ProviderSPI],
        logger: EventLogger | None = None,
        *,
        config: RunnerConfig | None = None,
    ) -> None:
        if not providers:
            raise ValueError("Runner requires at least one provider")
        self.providers: list[ProviderSPI] = list(providers)
        self._logger = logger
        self._config = config or RunnerConfig()
        self._rate_limiter: RateLimiter | None = resolve_rate_limiter(self._config.rpm)

    def _invoke_provider_sync(
        self,
        provider: ProviderSPI,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        event_logger: EventLogger | None,
        request_fingerprint: str,
        metadata: dict[str, object],
        shadow: ProviderSPI | None,
        metrics_path: MetricsPath,
        capture_shadow_metrics: bool,
    ) -> ProviderInvocationResult:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()
        attempt_started = time.time()
        response: ProviderResponse | None = None
        error: Exception | None = None
        latency_ms: int
        tokens_in: int | None = None
        tokens_out: int | None = None
        shadow_metrics: ShadowMetrics | None = None
        try:
            if capture_shadow_metrics:
                response_with_metrics = run_with_shadow(
                    provider,
                    shadow,
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
                response_only = run_with_shadow(
                    provider,
                    shadow,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=False,
                )
                response = cast(ProviderResponse, response_only)
        except Exception as exc:  # noqa: BLE001
            error = exc
            latency_ms = elapsed_ms(attempt_started)
            if isinstance(exc, ProviderSkip):
                log_provider_skipped(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt,
                    total_providers=total_providers,
                    error=exc,
                )
        else:
            latency_ms = response.latency_ms
            usage = response.token_usage
            tokens_in = usage.prompt
            tokens_out = usage.completion
        status = "ok" if error is None else "error"
        log_provider_call(
            event_logger,
            request_fingerprint=request_fingerprint,
            provider=provider,
            request=request,
            attempt=attempt,
            total_providers=total_providers,
            status=status,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
            metadata=metadata,
            shadow_used=shadow is not None,
        )
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=response,
            error=error,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            shadow_metrics=shadow_metrics,
            shadow_metrics_extra=None,
        )

    def _log_parallel_results(
        self,
        results: Sequence[ProviderInvocationResult | None],
        *,
        event_logger: EventLogger | None,
        request: ProviderRequest,
        request_fingerprint: str,
        metadata: dict[str, object],
        run_started: float,
        shadow_used: bool,
        attempt_count: int,
    ) -> None:
        for result in results:
            if result is None:
                continue
            if result.shadow_metrics is not None:
                result.shadow_metrics.emit(result.shadow_metrics_extra)
            status = "ok" if result.response is not None else "error"
            if status == "ok":
                tokens_in = result.tokens_in if result.tokens_in is not None else 0
                tokens_out = result.tokens_out if result.tokens_out is not None else 0
                cost_usd = estimate_cost(result.provider, tokens_in, tokens_out)
            else:
                tokens_in = None
                tokens_out = None
                cost_usd = 0.0
            latency_ms = result.latency_ms
            if latency_ms is None:
                latency_ms = elapsed_ms(run_started)
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=result.provider,
                status=status,
                attempts=attempt_count,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                error=None if status == "ok" else result.error,
                metadata=metadata,
                shadow_used=shadow_used,
            )

    def _extract_fatal_error(
        self, results: Sequence[ProviderInvocationResult | None]
    ) -> FatalError | None:
        for result in results:
            if result is None:
                continue
            error = result.error
            if isinstance(error, FatalError):
                return error
        return None

    def run(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        """Execute ``request`` with fallback semantics."""

        last_err: Exception | None = None
        event_logger, metrics_path_str = resolve_event_logger(
            self._logger, shadow_metrics_path
        )
        metadata = dict(request.metadata or {})
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )
        shadow_used = shadow is not None
        mode = self._config.mode

        if mode is RunnerMode.SEQUENTIAL:
            max_attempts = self._config.max_attempts
            attempt_count = 0
            for loop_index, provider in enumerate(self.providers, start=1):
                if max_attempts is not None and loop_index > max_attempts:
                    break
                attempt_index = loop_index
                attempt_count = attempt_index
                result = self._invoke_provider_sync(
                    provider,
                    request,
                    attempt=attempt_index,
                    total_providers=len(self.providers),
                    event_logger=event_logger,
                    request_fingerprint=request_fingerprint,
                    metadata=metadata,
                    shadow=shadow,
                    metrics_path=metrics_path_str,
                    capture_shadow_metrics=False,
                )
                if result.response is not None:
                    tokens_in = result.tokens_in if result.tokens_in is not None else 0
                    tokens_out = (
                        result.tokens_out if result.tokens_out is not None else 0
                    )
                    cost_usd = estimate_cost(
                        provider,
                        tokens_in,
                        tokens_out,
                    )
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
                        shadow_used=shadow_used,
                    )
                    return result.response
                error = result.error
                last_err = error
                if error is None:
                    continue
                if isinstance(error, FatalError):
                    raise error
                if isinstance(error, RateLimitError):
                    sleep_duration = self._config.backoff.rate_limit_sleep_s
                    if sleep_duration > 0:
                        time.sleep(sleep_duration)
                    continue
                if isinstance(error, RetryableError):
                    if isinstance(error, TimeoutError):
                        if not self._config.backoff.timeout_next_provider:
                            raise error
                        continue
                    if self._config.backoff.retryable_next_provider:
                        continue
                    raise error
                if isinstance(error, SkipError):
                    continue
                raise error

            if event_logger is not None:
                event_logger.emit(
                    "provider_chain_failed",
                    {
                        "request_fingerprint": request_fingerprint,
                        "provider_attempts": attempt_count,
                        "providers": [provider.name() for provider in self.providers],
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
                shadow_used=shadow_used,
            )
            raise last_err if last_err is not None else RuntimeError(
                "No providers succeeded"
            )

        total_providers = len(self.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers

        capture_shadow = mode is RunnerMode.CONSENSUS
        max_attempts = self._config.max_attempts
        attempt_lock = threading.Lock()
        attempts_used = 0
        retry_events = 0

        def reserve_attempt() -> int | None:
            nonlocal attempts_used
            with attempt_lock:
                if max_attempts is not None and attempts_used >= max_attempts:
                    return None
                attempts_used += 1
                return attempts_used

        def record_retry_event() -> int:
            nonlocal retry_events
            with attempt_lock:
                retry_events += 1
                return retry_events

        def snapshot_attempts() -> int:
            with attempt_lock:
                return attempts_used

        def compute_retry_delay(error: BaseException) -> float | None:
            if isinstance(error, RateLimitError):
                return max(self._config.backoff.rate_limit_sleep_s, 0.0)
            if isinstance(error, TimeoutError):
                return 0.0 if self._config.backoff.timeout_next_provider else None
            if isinstance(error, RetryableError):
                return 0.0 if self._config.backoff.retryable_next_provider else None
            return None

        def handle_parallel_retry(
            _worker_index: int, _attempt_index: int, _error: BaseException
        ) -> float | None:
            return None

        def make_worker(
            index: int,
            provider: ProviderSPI,
            *,
            allow_retry: bool,
        ) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                next_attempt = reserve_attempt()
                if next_attempt is None:
                    failure = ParallelExecutionError("max attempts exhausted")
                    result = ProviderInvocationResult(
                        provider=provider,
                        attempt=index,
                        total_providers=total_providers,
                        response=None,
                        error=failure,
                        latency_ms=None,
                        tokens_in=None,
                        tokens_out=None,
                        shadow_metrics=None,
                        shadow_metrics_extra=None,
                    )
                    results[index - 1] = result
                    raise failure
                attempt_index = next_attempt
                while True:
                    result = self._invoke_provider_sync(
                        provider,
                        request,
                        attempt=attempt_index,
                        total_providers=total_providers,
                        event_logger=event_logger,
                        request_fingerprint=request_fingerprint,
                        metadata=metadata,
                        shadow=shadow,
                        metrics_path=metrics_path_str,
                        capture_shadow_metrics=capture_shadow,
                    )
                    results[index - 1] = result
                    if result.response is not None:
                        return result
                    err = result.error
                    if err is None:
                        err = ParallelExecutionError("provider returned no response")
                        result.error = err
                    delay = compute_retry_delay(err) if allow_retry else None
                    if delay is None:
                        raise err
                    next_attempt = reserve_attempt()
                    if next_attempt is None:
                        raise err
                    retry_attempt = record_retry_event()
                    if event_logger is not None:
                        event_logger.emit(
                            "retry",
                            {
                                "request_fingerprint": request_fingerprint,
                                "provider": provider.name(),
                                "attempt": attempt_index,
                                "retry_attempt": retry_attempt,
                                "error_type": type(err).__name__,
                            },
                        )
                    if delay > 0:
                        time.sleep(delay)
                    attempt_index = next_attempt

            return worker

        workers = [
            make_worker(index, provider, allow_retry=mode is RunnerMode.PARALLEL_ANY)
            for index, provider in enumerate(self.providers, start=1)
        ]

        try:
            if mode is RunnerMode.PARALLEL_ANY:
                winner = run_parallel_any_sync(
                    workers, max_concurrency=self._config.max_concurrency
                )
                fatal = self._extract_fatal_error(results)
                if fatal is not None:
                    raise fatal from None
                response = winner.response
                if response is None:
                    raise ParallelExecutionError("all workers failed")
                attempts_final = snapshot_attempts()
                tokens_in = response.token_usage.prompt
                tokens_out = response.token_usage.completion
                cost_usd = estimate_cost(winner.provider, tokens_in, tokens_out)
                log_run_metric(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    request=request,
                    provider=winner.provider,
                    status="ok",
                    attempts=attempts_final,
                    latency_ms=elapsed_ms(run_started),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    error=None,
                    metadata=metadata,
                    shadow_used=shadow_used,
                )
                return response

            if mode is RunnerMode.PARALLEL_ALL:
                invocations = run_parallel_all_sync(
                    workers,
                    max_concurrency=self._config.max_concurrency,
                    max_attempts=self._config.max_attempts,
                    on_retry=handle_parallel_retry,
                )
                fatal = self._extract_fatal_error(results)
                if fatal is not None:
                    raise fatal from None
                for invocation in invocations:
                    if invocation.response is None:
                        raise ParallelExecutionError("all workers failed")
                return ParallelAllResult(
                    invocations,
                    lambda invocation: cast(ProviderResponse, invocation.response),
                )

            if mode is RunnerMode.CONSENSUS:
                invocations = run_parallel_all_sync(
                    workers,
                    max_concurrency=self._config.max_concurrency,
                    max_attempts=self._config.max_attempts,
                    on_retry=handle_parallel_retry,
                )
                fatal = self._extract_fatal_error(results)
                if fatal is not None:
                    raise fatal from None
                successful: list[
                    tuple[ProviderInvocationResult, ProviderResponse]
                ] = [
                    (res, res.response)
                    for res in invocations
                    if res.response is not None
                ]
                if len(successful) != len(invocations):
                    raise ParallelExecutionError("all workers failed")
                responses_for_consensus = [response for _, response in successful]
                consensus = compute_consensus(
                    responses_for_consensus,
                    config=self._config.consensus,
                )
                winner_invocation = next(
                    invocation
                    for invocation, response in successful
                    if response is consensus.response
                )
                votes_against = consensus.total_voters - consensus.votes - consensus.abstained
                if event_logger is not None:
                    candidate_summaries = [
                        {
                            "provider": invocation.provider.name(),
                            "latency_ms": response.latency_ms,
                            "votes": consensus.tally.get(
                                response.text.strip(), 0
                            ),
                            "text_hash": content_hash(
                                "consensus", response.text
                            ),
                        }
                        for invocation, response in successful
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
                                "winner_provider": winner_invocation.provider.name(),
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
                            },
                        )
                if winner_invocation.shadow_metrics is not None:
                    shadow_payload = winner_invocation.shadow_metrics.payload
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
                        }
                    }
                    if not shadow_payload.get("shadow_ok", True):
                        error = shadow_payload.get("shadow_error")
                        if error is not None:
                            extra["shadow_consensus_error"] = error
                    winner_invocation.shadow_metrics_extra = extra
                return consensus.response
        except ParallelExecutionError as exc:
            fatal = self._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            self._log_parallel_results(
                results,
                event_logger=event_logger,
                request=request,
                request_fingerprint=request_fingerprint,
                metadata=metadata,
                run_started=run_started,
                shadow_used=shadow_used,
                attempt_count=snapshot_attempts(),
            )

        raise RuntimeError(f"Unsupported runner mode: {mode}")


__all__ = ["Runner"]
