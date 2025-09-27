"""Synchronous runner implementation."""

from __future__ import annotations

import time
from collections.abc import Sequence

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
from .runner_config import RunnerConfig
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
        metadata = request.metadata or {}
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )

        max_attempts = self._config.max_attempts
        attempt_count = 0
        for loop_index, provider in enumerate(self.providers, start=1):
            if max_attempts is not None and loop_index > max_attempts:
                break
            attempt_index = loop_index
            attempt_count = attempt_index
            attempt_started = time.time()
            try:
                response = run_with_shadow(
                    provider,
                    shadow,
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
                )
                sleep_duration = self._config.backoff.rate_limit_sleep_s
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
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
            shadow_used=shadow is not None,
        )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")


__all__ = ["Runner"]
