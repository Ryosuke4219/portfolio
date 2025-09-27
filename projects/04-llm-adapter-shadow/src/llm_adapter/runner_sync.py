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
    provider_model,
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

        def _record_skip(err: SkipError, attempt: int, provider: ProviderSPI) -> None:
            if event_logger is None:
                return
            event_logger.emit(
                "provider_skipped",
                {
                    "request_fingerprint": request_fingerprint,
                    "request_hash": content_hash(
                        provider.name(),
                        request.prompt_text,
                        request.options,
                        request.max_tokens,
                    ),
                    "provider": provider.name(),
                    "attempt": attempt,
                    "total_providers": len(self.providers),
                    "reason": err.reason if hasattr(err, "reason") else None,
                    "error_message": str(err),
                },
            )

        def _log_provider_call(
            provider: ProviderSPI,
            attempt: int,
            *,
            status: str,
            latency_ms: int | None,
            tokens_in: int | None,
            tokens_out: int | None,
            error: Exception | None = None,
        ) -> None:
            if event_logger is None:
                return

            error_type = type(error).__name__ if error is not None else None
            error_message = str(error) if error is not None else None
            error_family_value = error_family(error)

            event_logger.emit(
                "provider_call",
                {
                    "request_fingerprint": request_fingerprint,
                    "request_hash": content_hash(
                        provider.name(),
                        request.prompt_text,
                        request.options,
                        request.max_tokens,
                    ),
                    "provider": provider.name(),
                    "model": provider_model(provider),
                    "attempt": attempt,
                    "total_providers": len(self.providers),
                    "status": status,
                    "latency_ms": latency_ms,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_family": error_family_value,
                    "shadow_used": shadow is not None,
                    "trace_id": metadata.get("trace_id"),
                    "project_id": metadata.get("project_id"),
                },
            )

        def _log_run_metric(
            *,
            status: str,
            provider: ProviderSPI | None,
            attempts: int,
            latency_ms: int,
            tokens_in: int | None,
            tokens_out: int | None,
            cost_usd: float,
            error: Exception | None,
        ) -> None:
            if event_logger is None:
                return

            error_type = type(error).__name__ if error else None
            error_message = str(error) if error else None
            error_family_value = error_family(error)
            provider_name = provider.name() if provider is not None else None
            request_hash = (
                content_hash(
                    provider_name,
                    request.prompt_text,
                    request.options,
                    request.max_tokens,
                )
                if provider_name
                else None
            )

            event_logger.emit(
                "run_metric",
                {
                    "request_fingerprint": request_fingerprint,
                    "request_hash": request_hash,
                    "provider": provider_name,
                    "status": status,
                    "attempts": attempts,
                    "latency_ms": latency_ms,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": float(cost_usd),
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_family": error_family_value,
                    "shadow_used": shadow is not None,
                    "trace_id": metadata.get("trace_id"),
                    "project_id": metadata.get("project_id"),
                },
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
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                sleep_duration = self._config.backoff.rate_limit_sleep_s
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
            except RetryableError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
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
                    _record_skip(err, attempt_index, provider)
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                continue
            except FatalError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                raise
            else:
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="ok",
                    latency_ms=response.latency_ms,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=None,
                )
                tokens_in = response.input_tokens
                tokens_out = response.output_tokens
                cost_usd = estimate_cost(provider, tokens_in, tokens_out)
                _log_run_metric(
                    status="ok",
                    provider=provider,
                    attempts=attempt_index,
                    latency_ms=elapsed_ms(run_started),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    error=None,
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
        _log_run_metric(
            status="error",
            provider=None,
            attempts=attempt_count,
            latency_ms=elapsed_ms(run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=last_err,
        )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")


__all__ = ["Runner"]
