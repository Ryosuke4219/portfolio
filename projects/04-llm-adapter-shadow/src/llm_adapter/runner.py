"""Provider runner with fallback handling."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import ProviderSkip, RateLimitError, RetriableError, TimeoutError
from .metrics import log_event
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow
from .utils import content_hash, elapsed_ms

MetricsPath = str | Path | None


@dataclass(frozen=True)
class BackoffPolicy:
    """Backoff configuration applied when providers fail."""

    rate_limit_seconds: float = 0.05


@dataclass(frozen=True)
class RunnerConfig:
    """Execution configuration for the provider runner."""

    max_attempts: int | None = None
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)

    def attempts_budget(self, total: int) -> int:
        if self.max_attempts is None:
            return total
        return max(0, min(total, self.max_attempts))


class EventLogger:
    """Convenience wrapper for structured logging of runner events."""

    def __init__(
        self,
        *,
        metrics_path: MetricsPath,
        request: ProviderRequest,
        total_providers: int,
        shadow: ProviderSPI | None,
    ) -> None:
        self._metrics_path = None if metrics_path is None else str(Path(metrics_path))
        self._request = request
        self._total_providers = total_providers
        self._shadow = shadow
        self._metadata: dict[str, Any] = request.metadata or {}
        self._request_fingerprint = content_hash(
            "runner", request.prompt_text, request.options, request.max_tokens
        )

    def enabled(self) -> bool:
        return self._metrics_path is not None

    def _provider_request_hash(self, provider: ProviderSPI | None) -> str | None:
        if provider is None:
            return None
        return content_hash(
            provider.name(),
            self._request.prompt_text,
            self._request.options,
            self._request.max_tokens,
        )

    def _provider_model(self, provider: ProviderSPI) -> str | None:
        for attr in ("model", "_model"):
            value = getattr(provider, attr, None)
            if isinstance(value, str) and value:
                return value
        return None

    def record_skip(self, provider: ProviderSPI, attempt: int, error: ProviderSkip) -> None:
        if not self.enabled():
            return
        log_event(
            "provider_skipped",
            self._metrics_path,
            request_fingerprint=self._request_fingerprint,
            request_hash=self._provider_request_hash(provider),
            provider=provider.name(),
            attempt=attempt,
            total_providers=self._total_providers,
            reason=error.reason if hasattr(error, "reason") else None,
            error_message=str(error),
        )

    def log_provider_call(
        self,
        *,
        provider: ProviderSPI,
        attempt: int,
        status: str,
        latency_ms: int | None,
        tokens_in: int | None,
        tokens_out: int | None,
        error: Exception | None,
    ) -> None:
        if not self.enabled():
            return
        error_type = type(error).__name__ if error is not None else None
        error_message = str(error) if error is not None else None
        log_event(
            "provider_call",
            self._metrics_path,
            request_fingerprint=self._request_fingerprint,
            request_hash=self._provider_request_hash(provider),
            provider=provider.name(),
            model=self._provider_model(provider),
            attempt=attempt,
            total_providers=self._total_providers,
            status=status,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error_type=error_type,
            error_message=error_message,
            shadow_used=self._shadow is not None,
            trace_id=self._metadata.get("trace_id"),
            project_id=self._metadata.get("project_id"),
        )

    def log_run_metric(
        self,
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
        if not self.enabled():
            return
        error_type = type(error).__name__ if error else None
        error_message = str(error) if error else None
        provider_name = provider.name() if provider is not None else None
        log_event(
            "run_metric",
            self._metrics_path,
            request_fingerprint=self._request_fingerprint,
            request_hash=self._provider_request_hash(provider),
            provider=provider_name,
            status=status,
            attempts=attempts,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=float(cost_usd),
            error_type=error_type,
            error_message=error_message,
            shadow_used=self._shadow is not None,
            trace_id=self._metadata.get("trace_id"),
            project_id=self._metadata.get("project_id"),
        )

    def log_chain_failure(self, providers: Sequence[ProviderSPI], last_error: Exception | None) -> None:
        if not self.enabled():
            return
        log_event(
            "provider_chain_failed",
            self._metrics_path,
            request_fingerprint=self._request_fingerprint,
            provider_attempts=len(providers),
            providers=[provider.name() for provider in providers],
            last_error_type=type(last_error).__name__ if last_error else None,
            last_error_message=str(last_error) if last_error else None,
        )


class Runner:
    """Attempt providers sequentially until one succeeds."""

    def __init__(
        self,
        providers: Sequence[ProviderSPI],
        *,
        config: RunnerConfig | None = None,
    ) -> None:
        if not providers:
            raise ValueError("Runner requires at least one provider")
        self.providers: list[ProviderSPI] = list(providers)
        self._config = config or RunnerConfig()

    def run(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
        *,
        config: RunnerConfig | None = None,
        event_logger: EventLogger | None = None,
    ) -> ProviderResponse:
        """Execute ``request`` with fallback semantics."""

        last_err: Exception | None = None
        metadata = request.metadata or {}
        run_started = time.time()
        resolved_config = config or self._config
        attempts_budget = resolved_config.attempts_budget(len(self.providers))
        providers = self.providers[:attempts_budget]
        active_logger = event_logger or EventLogger(
            metrics_path=shadow_metrics_path,
            request=request,
            total_providers=len(self.providers),
            shadow=shadow,
        )

        for attempt_index, provider in enumerate(providers, start=1):
            attempt_started = time.time()
            try:
                response = self._invoke_provider(provider, shadow, request, shadow_metrics_path)
            except ProviderSkip as err:
                last_err = err
                active_logger.record_skip(provider, attempt_index, err)
                active_logger.log_provider_call(
                    provider=provider,
                    attempt=attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                continue
            except RateLimitError as err:
                last_err = err
                active_logger.log_provider_call(
                    provider=provider,
                    attempt=attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                self._sleep_on_rate_limit(resolved_config.backoff)
            except (TimeoutError, RetriableError) as err:
                last_err = err
                active_logger.log_provider_call(
                    provider=provider,
                    attempt=attempt_index,
                    status="error",
                    latency_ms=elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                continue
            else:
                active_logger.log_provider_call(
                    provider=provider,
                    attempt=attempt_index,
                    status="ok",
                    latency_ms=response.latency_ms,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=None,
                )
                tokens_in = response.input_tokens
                tokens_out = response.output_tokens
                cost_usd = self._estimate_cost(provider, tokens_in, tokens_out)
                active_logger.log_run_metric(
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

        active_logger.log_chain_failure(providers, last_err)
        active_logger.log_run_metric(
            status="error",
            provider=None,
            attempts=len(providers),
            latency_ms=elapsed_ms(run_started),
            tokens_in=None,
            tokens_out=None,
            cost_usd=0.0,
            error=last_err,
        )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")

    def _invoke_provider(
        self,
        provider: ProviderSPI,
        shadow: ProviderSPI | None,
        request: ProviderRequest,
        metrics_path: MetricsPath,
    ) -> ProviderResponse:
        metrics_path_str = None if metrics_path is None else str(Path(metrics_path))
        return run_with_shadow(provider, shadow, request, metrics_path=metrics_path_str)

    def _sleep_on_rate_limit(self, backoff: BackoffPolicy) -> None:
        if backoff.rate_limit_seconds <= 0:
            return
        time.sleep(backoff.rate_limit_seconds)

    def _estimate_cost(self, provider: ProviderSPI, tokens_in: int, tokens_out: int) -> float:
        estimator = getattr(provider, "estimate_cost", None)
        if callable(estimator):
            try:
                return float(estimator(tokens_in, tokens_out))
            except Exception:  # pragma: no cover - defensive guard
                return 0.0
        return 0.0


__all__ = ["BackoffPolicy", "Runner", "RunnerConfig", "EventLogger"]
