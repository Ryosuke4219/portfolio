"""Synchronous runner strategy implementations."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import time
from typing import cast, Protocol, TYPE_CHECKING

from .errors import (
    AllFailedError,
    AuthError,
    ConfigError,
    FatalError,
    ProviderSkip,
    RateLimitError,
    RetryableError,
    SkipError,
    TimeoutError,
)
from .observability import EventLogger
from .parallel_exec import ParallelAllResult, ParallelExecutionError
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerMode
from .runner_parallel import compute_consensus
from .runner_shared import error_family, estimate_cost, log_run_metric, MetricsPath
from .shadow import ShadowMetrics
from .utils import content_hash, elapsed_ms

if TYPE_CHECKING:
    from .runner_sync import ProviderInvocationResult, Runner


class ParallelAllCallable(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], ProviderInvocationResult]],
        *,
        max_concurrency: int | None = ...,
    ) -> Sequence[ProviderInvocationResult]:
        ...


class ParallelAnyCallable(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], ProviderInvocationResult]],
        *,
        max_concurrency: int | None = ...,
    ) -> ProviderInvocationResult:
        ...


@dataclass(slots=True)
class SyncRunContext:
    runner: Runner
    request: ProviderRequest
    event_logger: EventLogger | None
    metadata: dict[str, object]
    run_started: float
    request_fingerprint: str
    shadow: ProviderSPI | None
    shadow_used: bool
    metrics_path: MetricsPath
    run_parallel_all: ParallelAllCallable
    run_parallel_any: ParallelAnyCallable


class SyncRunStrategy(Protocol):
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        ...


def _limited_providers(
    providers: Sequence[ProviderSPI], max_attempts: int | None
) -> Sequence[ProviderSPI]:
    if max_attempts is None:
        return providers
    if max_attempts <= 0:
        return ()
    return providers[:max_attempts]


def _raise_no_attempts(context: SyncRunContext) -> None:
    event_logger = context.event_logger
    runner = context.runner
    if event_logger is not None:
        event_logger.emit(
            "provider_chain_failed",
            {
                "request_fingerprint": context.request_fingerprint,
                "provider_attempts": 0,
                "providers": [provider.name() for provider in runner.providers],
                "last_error_type": None,
                "last_error_message": None,
                "last_error_family": None,
            },
        )
    log_run_metric(
        event_logger,
        request_fingerprint=context.request_fingerprint,
        request=context.request,
        provider=None,
        status="error",
        attempts=0,
        latency_ms=elapsed_ms(context.run_started),
        tokens_in=None,
        tokens_out=None,
        cost_usd=0.0,
        error=None,
        metadata=context.metadata,
        shadow_used=context.shadow_used,
    )
    raise AllFailedError()


class SequentialStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        config = runner._config
        max_attempts = config.max_attempts
        event_logger = context.event_logger
        last_err: Exception | None = None
        attempt_count = 0

        for loop_index, provider in enumerate(runner.providers, start=1):
            if max_attempts is not None and loop_index > max_attempts:
                break
            attempt_index = loop_index
            attempt_count = attempt_index
            result = runner._invoke_provider_sync(
                provider,
                context.request,
                attempt=attempt_index,
                total_providers=len(runner.providers),
                event_logger=event_logger,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                shadow=context.shadow,
                metrics_path=context.metrics_path,
                capture_shadow_metrics=False,
            )
            if result.response is not None:
                tokens_in = result.tokens_in if result.tokens_in is not None else 0
                tokens_out = result.tokens_out if result.tokens_out is not None else 0
                cost_usd = estimate_cost(provider, tokens_in, tokens_out)
                log_run_metric(
                    event_logger,
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
                    shadow_used=context.shadow_used,
                )
                return result.response

            error = result.error
            last_err = error
            if error is None:
                continue
            if isinstance(error, FatalError):
                if isinstance(error, (AuthError, ConfigError)):
                    if event_logger is not None:
                        event_logger.emit(
                            "provider_fallback",
                            {
                                "request_fingerprint": context.request_fingerprint,
                                "provider": provider.name(),
                                "attempt": attempt_index,
                                "error_type": type(error).__name__,
                                "error_message": str(error),
                            },
                        )
                    continue
                raise error
            if isinstance(error, RateLimitError):
                sleep_duration = config.backoff.rate_limit_sleep_s
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                continue
            if isinstance(error, RetryableError):
                if isinstance(error, TimeoutError):
                    if not config.backoff.timeout_next_provider:
                        raise error
                    continue
                if config.backoff.retryable_next_provider:
                    continue
                raise error
            if isinstance(error, (SkipError, ProviderSkip)):
                continue
            raise error

        if event_logger is not None:
            event_logger.emit(
                "provider_chain_failed",
                {
                    "request_fingerprint": context.request_fingerprint,
                    "provider_attempts": attempt_count,
                    "providers": [provider.name() for provider in runner.providers],
                    "last_error_type": type(last_err).__name__ if last_err else None,
                    "last_error_message": str(last_err) if last_err else None,
                    "last_error_family": error_family(last_err),
                },
            )
        log_run_metric(
            event_logger,
            request_fingerprint=context.request_fingerprint,
            request=context.request,
            provider=None,
            status="error",
            attempts=attempt_count,
            latency_ms=elapsed_ms(context.run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=last_err,
            metadata=context.metadata,
            shadow_used=context.shadow_used,
        )
        if last_err is not None:
            raise AllFailedError(last_error=last_err) from last_err
        raise AllFailedError()


class ParallelAnyStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        total_providers = len(runner.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = _limited_providers(runner.providers, max_attempts)

        def make_worker(index: int, provider: ProviderSPI) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=False,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            _raise_no_attempts(context)

        attempts_override: dict[int, int] | None = None
        try:
            winner = context.run_parallel_any(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            response = winner.response
            if response is None:
                raise ParallelExecutionError("all workers failed")
            attempts_final = sum(1 for item in results if item is not None)
            if attempts_final == 0:
                attempts_final = winner.attempt
            attempts_override = {winner.attempt: attempts_final}
            return response
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
                attempts_override=attempts_override,
            )


class ParallelAllStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        total_providers = len(runner.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = _limited_providers(runner.providers, max_attempts)

        def make_worker(index: int, provider: ProviderSPI) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=False,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            _raise_no_attempts(context)

        try:
            invocations = context.run_parallel_all(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            for invocation in invocations:
                if invocation.response is None:
                    raise ParallelExecutionError("all workers failed")
            return ParallelAllResult(
                invocations,
                lambda invocation: cast(ProviderResponse, invocation.response),
            )
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
            )


class ConsensusStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> ProviderResponse | ParallelAllResult[
        ProviderInvocationResult, ProviderResponse
    ]:
        runner = context.runner
        total_providers = len(runner.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = _limited_providers(runner.providers, max_attempts)

        def make_worker(index: int, provider: ProviderSPI) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=True,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            _raise_no_attempts(context)

        try:
            invocations = context.run_parallel_all(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            successful: list[tuple[ProviderInvocationResult, ProviderResponse]] = [
                (res, res.response)
                for res in invocations
                if res.response is not None
            ]
            if not successful:
                failure_details: list[dict[str, str]] = []
                for invocation in invocations:
                    provider_name = invocation.provider.name()
                    attempt_label = str(invocation.attempt)
                    error = invocation.error
                    summary = (
                        f"{type(error).__name__}: {error}"
                        if error is not None
                        else "unknown error"
                    )
                    failure_details.append(
                        {
                            "provider": provider_name,
                            "attempt": attempt_label,
                            "summary": summary,
                        }
                    )
                detail_text = "; ".join(
                    f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
                    for item in failure_details
                )
                message = "all workers failed"
                if detail_text:
                    message = f"{message}: {detail_text}"
                error = ParallelExecutionError(message, failures=failure_details)
                raise error
            responses_for_consensus = [response for _, response in successful]
            consensus = compute_consensus(
                responses_for_consensus,
                config=runner._config.consensus,
            )
            winner_invocation = next(
                invocation
                for invocation, response in successful
                if response is consensus.response
            )
            votes_against = (
                consensus.total_voters - consensus.votes - consensus.abstained
            )
            event_logger = context.event_logger
            if event_logger is not None:
                candidate_summaries = [
                    {
                        "provider": invocation.provider.name(),
                        "latency_ms": response.latency_ms,
                        "votes": consensus.tally.get(response.text.strip(), 0),
                        "text_hash": content_hash("consensus", response.text),
                    }
                    for invocation, response in successful
                ]
                event_logger.emit(
                    "consensus_vote",
                    {
                        "request_fingerprint": context.request_fingerprint,
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
                shadow_metrics = cast(ShadowMetrics, winner_invocation.shadow_metrics)
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
                    }
                }
                if not shadow_payload.get("shadow_ok", True):
                    error = shadow_payload.get("shadow_error")
                    if error is not None:
                        extra["shadow_consensus_error"] = error
                winner_invocation.shadow_metrics_extra = extra
            return consensus.response
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
            )


def get_sync_strategy(mode: RunnerMode) -> SyncRunStrategy:
    if mode == RunnerMode.SEQUENTIAL:
        return SequentialStrategy()
    if mode == RunnerMode.PARALLEL_ANY:
        return ParallelAnyStrategy()
    if mode == RunnerMode.PARALLEL_ALL:
        return ParallelAllStrategy()
    if mode == RunnerMode.CONSENSUS:
        return ConsensusStrategy()
    raise RuntimeError(f"Unsupported runner mode: {mode}")


__all__ = [
    "SyncRunContext",
    "SyncRunStrategy",
    "get_sync_strategy",
]
