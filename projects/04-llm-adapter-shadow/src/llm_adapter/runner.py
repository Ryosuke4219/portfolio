"""Provider runner with synchronous and asynchronous execution helpers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import FatalError, RateLimitError, RetryableError, SkipError
from .metrics import log_event
from .provider_spi import (
    AsyncProviderSPI,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
    ensure_async_provider,
)
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow, run_with_shadow_async
from .utils import content_hash

MetricsPath = str | Path | None


@dataclass(frozen=True)
class RunnerConfig:
    """Runtime configuration knobs for :class:`Runner` and :class:`AsyncRunner`."""

    rate_limit_backoff_s: float = 0.05


class Runner:
    """Attempt providers sequentially until one succeeds."""

    def __init__(self, providers: Sequence[ProviderSPI], *, config: RunnerConfig | None = None):
        if not providers:
            raise ValueError("Runner requires at least one provider")
        self.providers: list[ProviderSPI] = list(providers)
        self.config = config or RunnerConfig()

    def run(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse:
        """Execute ``request`` with fallback semantics."""

        last_err: Exception | None = None
        metrics_path_str = None if shadow_metrics_path is None else str(Path(shadow_metrics_path))
        metadata = request.metadata or {}
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )

        def _record_skip(err: SkipError, attempt: int, provider: ProviderSPI) -> None:
            if not metrics_path_str:
                return
            log_event(
                "provider_skipped",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(
                    provider.name(),
                    request.prompt_text,
                    request.options,
                    request.max_tokens,
                ),
                provider=provider.name(),
                attempt=attempt,
                total_providers=len(self.providers),
                reason=err.reason if hasattr(err, "reason") else None,
                error_message=str(err),
                error_family="skip",
            )

        def _elapsed_ms(start_ts: float) -> int:
            return max(0, int((time.time() - start_ts) * 1000))

        def _log_provider_call(
            provider: ProviderSPI,
            attempt: int,
            *,
            status: str,
            latency_ms: int | None,
            tokens_in: int | None,
            tokens_out: int | None,
            error: Exception | None = None,
            error_family: str | None = None,
        ) -> None:
            if not metrics_path_str:
                return

            error_type = type(error).__name__ if error is not None else None
            error_message = str(error) if error is not None else None

            provider_model = getattr(provider, "model", None)
            if not isinstance(provider_model, str) or not provider_model:
                provider_model = None

            log_event(
                "provider_call",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(
                    provider.name(),
                    request.prompt_text,
                    request.options,
                    request.max_tokens,
                ),
                provider=provider.name(),
                model=provider_model,
                attempt=attempt,
                total_providers=len(self.providers),
                status=status,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error_type=error_type,
                error_message=error_message,
                error_family=error_family,
                shadow_used=shadow is not None,
                trace_id=metadata.get("trace_id"),
                project_id=metadata.get("project_id"),
            )

        def _estimate_cost(provider: ProviderSPI, tokens_in: int, tokens_out: int) -> float:
            estimator = getattr(provider, "estimate_cost", None)
            if callable(estimator):
                try:
                    return float(estimator(tokens_in, tokens_out))
                except Exception:  # pragma: no cover - defensive guard
                    return 0.0
            return 0.0

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
            error_family: str | None,
        ) -> None:
            if not metrics_path_str:
                return

            error_type = type(error).__name__ if error else None
            error_message = str(error) if error else None
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

            log_event(
                "run_metric",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=request_hash,
                provider=provider_name,
                status=status,
                attempts=attempts,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(cost_usd),
                error_type=error_type,
                error_message=error_message,
                error_family=error_family,
                shadow_used=shadow is not None,
                trace_id=metadata.get("trace_id"),
                project_id=metadata.get("project_id"),
            )

        def _error_family(error: Exception | None) -> str | None:
            if error is None:
                return None
            if isinstance(error, SkipError):
                return "skip"
            if isinstance(error, FatalError):
                return "fatal"
            if isinstance(error, RetryableError):
                return "retryable"
            return None

        for attempt_index, provider in enumerate(self.providers, start=1):
            attempt_started = time.time()
            try:
                response = run_with_shadow(provider, shadow, request, metrics_path=metrics_path_str)
            except SkipError as err:
                last_err = err
                _record_skip(err, attempt_index, provider)
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    error_family="skip",
                )
                continue
            except FatalError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    error_family="fatal",
                )
                _log_run_metric(
                    status="error",
                    provider=provider,
                    attempts=attempt_index,
                    latency_ms=_elapsed_ms(run_started),
                    tokens_in=None,
                    tokens_out=None,
                    cost_usd=0.0,
                    error=err,
                    error_family="fatal",
                )
                raise
            except RetryableError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    error_family="retryable",
                )
                if isinstance(err, RateLimitError):
                    backoff = max(0.0, self.config.rate_limit_backoff_s)
                    if backoff > 0:
                        time.sleep(backoff)
                continue
            else:
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="ok",
                    latency_ms=response.latency_ms,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=None,
                    error_family=None,
                )
                tokens_in = response.input_tokens
                tokens_out = response.output_tokens
                cost_usd = _estimate_cost(provider, tokens_in, tokens_out)
                _log_run_metric(
                    status="ok",
                    provider=provider,
                    attempts=attempt_index,
                    latency_ms=_elapsed_ms(run_started),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    error=None,
                    error_family=None,
                )
                return response

        if metrics_path_str:
            log_event(
                "provider_chain_failed",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                provider_attempts=len(self.providers),
                providers=[provider.name() for provider in self.providers],
                last_error_type=type(last_err).__name__ if last_err else None,
                last_error_message=str(last_err) if last_err else None,
                error_family=_error_family(last_err),
            )
        _log_run_metric(
            status="error",
            provider=None,
            attempts=len(self.providers),
            latency_ms=_elapsed_ms(run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=last_err,
            error_family=_error_family(last_err),
        )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")


class AsyncRunner:
    """Async counterpart of :class:`Runner` providing ``asyncio`` bridges."""

    def __init__(
        self,
        providers: Sequence[ProviderSPI | AsyncProviderSPI],
        *,
        config: RunnerConfig | None = None,
    ):
        if not providers:
            raise ValueError("AsyncRunner requires at least one provider")
        self.providers: list[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]] = [
            (provider, ensure_async_provider(provider)) for provider in providers
        ]
        self.config = config or RunnerConfig()

    async def run_async(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | AsyncProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse:
        last_err: Exception | None = None
        metrics_path_str = None if shadow_metrics_path is None else str(Path(shadow_metrics_path))
        metadata = request.metadata or {}
        run_started = time.time()
        request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )

        shadow_async = ensure_async_provider(shadow) if shadow is not None else None

        def _record_skip(
            err: SkipError, attempt: int, provider: ProviderSPI | AsyncProviderSPI
        ) -> None:
            if not metrics_path_str:
                return
            log_event(
                "provider_skipped",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(
                    provider.name(),
                    request.prompt_text,
                    request.options,
                    request.max_tokens,
                ),
                provider=provider.name(),
                attempt=attempt,
                total_providers=len(self.providers),
                reason=err.reason if hasattr(err, "reason") else None,
                error_message=str(err),
                error_family="skip",
            )

        def _provider_model(provider: ProviderSPI | AsyncProviderSPI) -> str | None:
            for attr in ("model", "_model"):
                value = getattr(provider, attr, None)
                if isinstance(value, str) and value:
                    return value
            return None

        def _elapsed_ms(start_ts: float) -> int:
            return max(0, int((time.time() - start_ts) * 1000))

        def _log_provider_call(
            provider: ProviderSPI | AsyncProviderSPI,
            attempt: int,
            *,
            status: str,
            latency_ms: int | None,
            tokens_in: int | None,
            tokens_out: int | None,
            error: Exception | None = None,
            error_family: str | None = None,
        ) -> None:
            if not metrics_path_str:
                return

            error_type = type(error).__name__ if error is not None else None
            error_message = str(error) if error is not None else None

            log_event(
                "provider_call",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(
                    provider.name(),
                    request.prompt_text,
                    request.options,
                    request.max_tokens,
                ),
                provider=provider.name(),
                model=_provider_model(provider),
                attempt=attempt,
                total_providers=len(self.providers),
                status=status,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error_type=error_type,
                error_message=error_message,
                error_family=error_family,
                shadow_used=shadow is not None,
                trace_id=metadata.get("trace_id"),
                project_id=metadata.get("project_id"),
            )

        def _estimate_cost(
            provider: ProviderSPI | AsyncProviderSPI, tokens_in: int, tokens_out: int
        ) -> float:
            estimator = getattr(provider, "estimate_cost", None)
            if callable(estimator):
                try:
                    return float(estimator(tokens_in, tokens_out))
                except Exception:  # pragma: no cover - defensive guard
                    return 0.0
            return 0.0

        def _log_run_metric(
            *,
            status: str,
            provider: ProviderSPI | AsyncProviderSPI | None,
            attempts: int,
            latency_ms: int,
            tokens_in: int | None,
            tokens_out: int | None,
            cost_usd: float,
            error: Exception | None,
            error_family: str | None,
        ) -> None:
            if not metrics_path_str:
                return

            error_type = type(error).__name__ if error else None
            error_message = str(error) if error else None
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

            log_event(
                "run_metric",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=request_hash,
                provider=provider_name,
                status=status,
                attempts=attempts,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(cost_usd),
                error_type=error_type,
                error_message=error_message,
                error_family=error_family,
                shadow_used=shadow is not None,
                trace_id=metadata.get("trace_id"),
                project_id=metadata.get("project_id"),
            )

        def _error_family(error: Exception | None) -> str | None:
            if error is None:
                return None
            if isinstance(error, SkipError):
                return "skip"
            if isinstance(error, FatalError):
                return "fatal"
            if isinstance(error, RetryableError):
                return "retryable"
            return None

        for attempt_index, (provider, async_provider) in enumerate(self.providers, start=1):
            attempt_started = time.time()
            try:
                response = await run_with_shadow_async(
                    async_provider,
                    shadow_async,
                    request,
                    metrics_path=metrics_path_str,
                )
            except SkipError as err:
                last_err = err
                _record_skip(err, attempt_index, provider)
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    error_family="skip",
                )
                continue
            except FatalError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    error_family="fatal",
                )
                _log_run_metric(
                    status="error",
                    provider=provider,
                    attempts=attempt_index,
                    latency_ms=_elapsed_ms(run_started),
                    tokens_in=None,
                    tokens_out=None,
                    cost_usd=0.0,
                    error=err,
                    error_family="fatal",
                )
                raise
            except RetryableError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                    error_family="retryable",
                )
                if isinstance(err, RateLimitError):
                    backoff = max(0.0, self.config.rate_limit_backoff_s)
                    if backoff > 0:
                        await asyncio.sleep(backoff)
                continue
            else:
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="ok",
                    latency_ms=response.latency_ms,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=None,
                    error_family=None,
                )
                tokens_in = response.input_tokens
                tokens_out = response.output_tokens
                cost_usd = _estimate_cost(provider, tokens_in, tokens_out)
                _log_run_metric(
                    status="ok",
                    provider=provider,
                    attempts=attempt_index,
                    latency_ms=_elapsed_ms(run_started),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    error=None,
                    error_family=None,
                )
                return response

        if metrics_path_str:
            log_event(
                "provider_chain_failed",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                provider_attempts=len(self.providers),
                providers=[provider.name() for provider, _ in self.providers],
                last_error_type=type(last_err).__name__ if last_err else None,
                last_error_message=str(last_err) if last_err else None,
                error_family=_error_family(last_err),
            )
        _log_run_metric(
            status="error",
            provider=None,
            attempts=len(self.providers),
            latency_ms=_elapsed_ms(run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=last_err,
            error_family=_error_family(last_err),
        )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")


__all__ = ["Runner", "AsyncRunner", "RunnerConfig"]
