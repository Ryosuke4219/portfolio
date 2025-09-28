"""Synchronous runner implementation."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

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
    ParallelExecutionError,
    compute_consensus,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from .runner_shared import (
    MetricsPath,
    error_family,
    estimate_cost,
    log_provider_call,
    log_provider_skipped,
    log_run_metric,
    resolve_event_logger,
)
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow
from .utils import content_hash, elapsed_ms


@dataclass(slots=True)
class ProviderInvocationResult:
    provider: ProviderSPI
    attempt: int
    total_providers: int
    response: ProviderResponse | None
    error: Exception | None
    latency_ms: float
    tokens_in: int | None
    tokens_out: int | None


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
    ) -> ProviderInvocationResult:
        attempt_started = time.time()
        response: ProviderResponse | None = None
        error: Exception | None = None
        latency_ms: float
        tokens_in: int | None = None
        tokens_out: int | None = None
        try:
            response = run_with_shadow(
                provider,
                shadow,
                request,
                metrics_path=metrics_path,
                logger=event_logger,
            )
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
    ) -> None:
        for result in results:
            if result is None:
                continue
            status = "ok" if result.response is not None else "error"
            tokens_in = result.tokens_in if status == "ok" else None
            tokens_out = result.tokens_out if status == "ok" else None
            cost_usd = 0.0
            if status == "ok":
                cost_usd = estimate_cost(result.provider, tokens_in, tokens_out)
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=result.provider,
                status=status,
                attempts=result.attempt,
                latency_ms=elapsed_ms(run_started),
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
    ) -> ProviderResponse:
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
                )
                if result.response is not None:
                    tokens_in = result.tokens_in
                    tokens_out = result.tokens_out
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

        def make_worker(index: int, provider: ProviderSPI):
            def worker() -> ProviderInvocationResult:
                result = self._invoke_provider_sync(
                    provider,
                    request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=event_logger,
                    request_fingerprint=request_fingerprint,
                    metadata=metadata,
                    shadow=shadow,
                    metrics_path=metrics_path_str,
                )
                results[index - 1] = result
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(self.providers, start=1)
        ]

        try:
            if mode is RunnerMode.PARALLEL_ANY:
                winner = run_parallel_any_sync(
                    workers, max_concurrency=self._config.max_concurrency
                )
                fatal = self._extract_fatal_error(results)
                if fatal is not None:
                    raise fatal
                if winner.response is None:
                    raise ParallelExecutionError("all workers failed")
                return winner.response

            if mode is RunnerMode.PARALLEL_ALL:
                responses = run_parallel_all_sync(
                    workers, max_concurrency=self._config.max_concurrency
                )
                fatal = self._extract_fatal_error(results)
                if fatal is not None:
                    raise fatal
                for response in responses:
                    if response.response is None:
                        raise ParallelExecutionError("all workers failed")
                return responses[0].response

            if mode is RunnerMode.CONSENSUS:
                responses = run_parallel_all_sync(
                    workers, max_concurrency=self._config.max_concurrency
                )
                fatal = self._extract_fatal_error(results)
                if fatal is not None:
                    raise fatal
                provider_responses = [
                    res.response
                    for res in responses
                    if res.response is not None
                ]
                if len(provider_responses) != len(responses):
                    raise ParallelExecutionError("all workers failed")
                consensus = compute_consensus(
                    provider_responses, config=self._config.consensus
                )
                return consensus.response
        except ParallelExecutionError as exc:
            fatal = self._extract_fatal_error(results)
            if fatal is not None:
                raise fatal
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
            )

        raise RuntimeError(f"Unsupported runner mode: {mode}")


__all__ = ["Runner"]
