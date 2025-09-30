"""Async runner strategies and shared utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence

from .errors import FatalError, RateLimitError, RetryableError, SkipError, TimeoutError
from .observability import EventLogger
from .parallel_exec import (
    ParallelAllResult,
    ParallelExecutionError,
    run_parallel_all_async,
    run_parallel_any_async,
)
from .provider_spi import AsyncProviderSPI, ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerConfig, RunnerMode
from .runner_parallel import compute_consensus
from .runner_shared import estimate_cost, log_run_metric
from .shadow import ShadowMetrics
from .utils import content_hash, elapsed_ms

WorkerResult = tuple[
    int,
    ProviderSPI | AsyncProviderSPI,
    ProviderResponse,
    ShadowMetrics | None,
]
WorkerFactory = Callable[[], Awaitable[WorkerResult]]


InvokeProviderFn = Callable[
    [
        int,
        ProviderSPI | AsyncProviderSPI,
        AsyncProviderSPI,
        bool,
    ],
    Awaitable[tuple[ProviderResponse, ShadowMetrics | None]],
]


@dataclass
class AsyncRunContext:
    request: ProviderRequest
    providers: Sequence[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]]
    event_logger: EventLogger | None
    metadata: Mapping[str, Any]
    request_fingerprint: str
    run_started: float
    shadow: ProviderSPI | AsyncProviderSPI | None
    shadow_async: AsyncProviderSPI | None
    metrics_path: str | None
    config: RunnerConfig
    mode: RunnerMode
    invoke_provider: InvokeProviderFn
    sleep_fn: Callable[[float], Awaitable[None]]
    attempt_count: int = 0
    last_error: Exception | None = None
    results: list[WorkerResult] | None = None
    failure_records: list[dict[str, str] | None] = field(default_factory=list)
    attempted: list[bool] = field(default_factory=list)
    attempt_labels: list[int] = field(default_factory=list)
    pending_retry_events: dict[int, dict[str, Any]] = field(default_factory=dict)
    retry_attempts: int = 0

    def __post_init__(self) -> None:
        total = len(self.providers)
        if not self.failure_records:
            self.failure_records = [None] * total
        if not self.attempted:
            self.attempted = [False] * total
        if not self.attempt_labels:
            self.attempt_labels = [index for index in range(1, total + 1)]

    @property
    def total_providers(self) -> int:
        return len(self.providers)


@dataclass
class StrategyResult:
    value: ProviderResponse | ParallelAllResult[WorkerResult, ProviderResponse] | None
    attempt_count: int
    last_error: Exception | None
    results: list[WorkerResult] | None = None
    failure_details: list[dict[str, str]] | None = None


class AsyncRunStrategy(Protocol):
    async def run(self, context: AsyncRunContext) -> StrategyResult:  # pragma: no cover - protocol
        ...


def collect_failure_details(context: AsyncRunContext) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for index, was_attempted in enumerate(context.attempted):
        if not was_attempted:
            continue
        record = context.failure_records[index]
        if record is not None:
            details.append(dict(record))
            continue
        provider, _ = context.providers[index]
        details.append(
            {
                "provider": provider.name(),
                "attempt": str(context.attempt_labels[index]),
                "summary": "unknown error",
            }
        )
    return details


def compute_parallel_retry_decision(
    *,
    error: BaseException,
    is_parallel_any: bool,
    context: AsyncRunContext,
) -> tuple[int, float] | None:
    next_attempt_total = context.total_providers + context.retry_attempts + 1
    delay: float | None = None
    if isinstance(error, RateLimitError):
        delay = context.config.backoff.rate_limit_sleep_s
    elif isinstance(error, TimeoutError):
        if not context.config.backoff.timeout_next_provider:
            delay = 0.0
    elif isinstance(error, RetryableError):
        if not context.config.backoff.retryable_next_provider:
            delay = 0.0
    elif is_parallel_any:
        return None
    if delay is None:
        return None
    delay = max(0.0, float(delay))
    limit = context.config.max_attempts
    if limit is not None and next_attempt_total > limit:
        return None
    return next_attempt_total, delay


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


class ParallelStrategyBase:
    def __init__(self, *, capture_shadow_metrics: bool, is_parallel_any: bool) -> None:
        self._capture_shadow_metrics = capture_shadow_metrics
        self._is_parallel_any = is_parallel_any

    def _reset_context(self, context: AsyncRunContext) -> None:
        total = context.total_providers
        context.attempt_count = total
        context.retry_attempts = 0
        context.results = None
        context.last_error = None
        context.failure_records = [None] * total
        context.attempted = [False] * total
        context.attempt_labels = [index for index in range(1, total + 1)]
        context.pending_retry_events.clear()

    def _build_worker(
        self,
        context: AsyncRunContext,
        worker_index: int,
        provider: ProviderSPI | AsyncProviderSPI,
        async_provider: AsyncProviderSPI,
    ) -> WorkerFactory:
        async def _worker() -> WorkerResult:
            attempt_index = context.attempt_labels[worker_index]
            if context.event_logger is not None:
                pending_payload = context.pending_retry_events.pop(worker_index, None)
                if (
                    pending_payload is not None
                    and pending_payload.get("next_attempt") == attempt_index
                ):
                    context.event_logger.emit("retry", pending_payload)
                elif pending_payload is not None:
                    context.pending_retry_events[worker_index] = pending_payload
            context.attempted[worker_index] = True
            try:
                response, shadow_metrics = await context.invoke_provider(
                    attempt_index,
                    provider,
                    async_provider,
                    self._capture_shadow_metrics,
                )
            except Exception as exc:  # noqa: BLE001
                context.failure_records[worker_index] = {
                    "provider": provider.name(),
                    "attempt": str(attempt_index),
                    "summary": f"{type(exc).__name__}: {exc}",
                }
                raise
            context.failure_records[worker_index] = None
            return attempt_index, provider, response, shadow_metrics

        return _worker

    async def _on_retry(
        self,
        context: AsyncRunContext,
        worker_index: int,
        attempt_index: int,
        error: BaseException,
    ) -> tuple[int, float] | None:
        decision = compute_parallel_retry_decision(
            error=error,
            is_parallel_any=self._is_parallel_any,
            context=context,
        )
        if decision is None:
            return None
        next_attempt_total, delay = decision
        retry_attempt = context.retry_attempts + 1
        context.retry_attempts = retry_attempt
        context.attempt_count = next_attempt_total
        context.attempt_labels[worker_index] = next_attempt_total
        if context.event_logger is not None:
            provider, _ = context.providers[worker_index]
            context.pending_retry_events[worker_index] = {
                "request_fingerprint": context.request_fingerprint,
                "provider": provider.name(),
                "attempt": attempt_index,
                "retry_attempt": retry_attempt,
                "next_attempt": next_attempt_total,
                "error_type": type(error).__name__,
                "delay_seconds": delay,
            }
        return next_attempt_total, delay

    def _create_workers(self, context: AsyncRunContext) -> list[WorkerFactory]:
        return [
            self._build_worker(context, index, provider, async_provider)
            for index, (provider, async_provider) in enumerate(context.providers)
        ]


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
        attempt_index, provider, response, _metrics = results[0]
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
            attempts=context.attempt_count,
            latency_ms=elapsed_ms(context.run_started),
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


class ConsensusRunStrategy(ParallelStrategyBase):
    def __init__(self) -> None:
        super().__init__(capture_shadow_metrics=True, is_parallel_any=False)

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
            return StrategyResult(None, context.attempt_count, context.last_error)

        context.results = results
        successful_entries = [
            entry for entry in results if len(entry) >= 3 and entry[2] is not None
        ]
        if not successful_entries:
            failure_details = collect_failure_details(context)
            detail_text = "; ".join(
                f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
                for item in failure_details
            )
            message = "all workers failed"
            if detail_text:
                message = f"{message}: {detail_text}"
            context.last_error = ParallelExecutionError(
                message, failures=failure_details or None
            )
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                results=results,
                failure_details=failure_details,
            )

        try:
            consensus = compute_consensus(
                [response for _, _, response, _ in successful_entries],
                config=context.config.consensus,
            )
        except ParallelExecutionError as err:
            context.last_error = err
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                results=results,
            )

        try:
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
        except StopIteration:
            context.last_error = ParallelExecutionError("consensus resolution failed")
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                results=results,
            )
        attempt_index, provider, response, shadow_metrics = winner_entry
        votes_against = consensus.total_voters - consensus.votes - consensus.abstained
        if context.event_logger is not None:
            candidate_summaries = [
                {
                    "provider": prov.name(),
                    "latency_ms": resp.latency_ms,
                    "votes": consensus.tally.get(resp.text.strip(), 0),
                    "text_hash": content_hash("consensus", resp.text),
                }
                for _attempt, prov, resp, _ in successful_entries
            ]
            context.event_logger.emit(
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
                    "winner_provider": provider.name(),
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
            attempts=context.attempt_count,
            latency_ms=elapsed_ms(context.run_started),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            error=None,
            metadata=context.metadata,
            shadow_used=context.shadow is not None,
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
                }
            }
            if not shadow_payload.get("shadow_ok", True):
                error = shadow_payload.get("shadow_error")
                if error is not None:
                    extra["shadow_consensus_error"] = error
            shadow_metrics.emit(extra)
        for _, _, _, metrics in results:
            if metrics is not None and metrics is not shadow_metrics:
                metrics.emit()
        return StrategyResult(response, context.attempt_count, None, results=results)

