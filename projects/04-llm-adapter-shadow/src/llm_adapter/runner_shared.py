"""Shared helpers for runner modules."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable

from .errors import FatalError, RateLimitError, RetryableError, SkipError
from .observability import EventLogger, JsonlLogger
from .runner_config import RunnerConfig
from .utils import content_hash

if TYPE_CHECKING:
    from .provider_spi import AsyncProviderSPI, ProviderRequest, ProviderSPI


class TokenPermit:
    """Handle returned by :class:`TokenBucket` acquisitions."""

    __slots__ = ("_committed",)

    def __init__(self) -> None:
        self._committed = False

    def commit(self) -> None:
        """Finalize the permit (idempotent)."""

        if self._committed:
            return
        self._committed = True


class TokenBucket:
    """Simple token bucket enforcing request-per-minute constraints."""

    __slots__ = (
        "_capacity",
        "_tokens",
        "_refill_rate",
        "_last_refill",
        "_clock",
        "_lock",
    )

    def __init__(
        self,
        rpm: int,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self._refill_rate = float(rpm) / 60.0
        self._capacity = max(1.0, self._refill_rate)
        self._tokens = self._capacity
        self._clock = clock or time.monotonic
        self._last_refill = self._clock()
        self._lock = Lock()

    def _refill(self, now: float) -> None:
        if self._tokens >= self._capacity:
            self._last_refill = now
            return
        elapsed = max(0.0, now - self._last_refill)
        if elapsed <= 0.0:
            return
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._refill_rate,
        )
        self._last_refill = now

    def _reserve(self) -> float:
        with self._lock:
            now = self._clock()
            self._refill(now)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            deficit = 1.0 - self._tokens
            wait_time = deficit / self._refill_rate
        return max(wait_time, 0.0)

    def acquire(self) -> TokenPermit:
        """Block until a token can be consumed and return a permit."""

        while True:
            wait_time = self._reserve()
            if wait_time <= 0.0:
                break
            time.sleep(wait_time)
        return TokenPermit()

    async def acquire_async(self) -> TokenPermit:
        """Async variant of :meth:`acquire`."""

        while True:
            wait_time = self._reserve()
            if wait_time <= 0.0:
                break
            await asyncio.sleep(wait_time)
        return TokenPermit()


def token_bucket_from_config(config: RunnerConfig) -> TokenBucket | None:
    """Build a token bucket from ``config`` if an RPM limit is set."""

    if config.rpm is None:
        return None
    return TokenBucket(config.rpm)

MetricsPath = str | Path | None


def resolve_event_logger(
    logger: EventLogger | None,
    metrics_path: MetricsPath,
) -> tuple[EventLogger | None, str | None]:
    """Resolve the event logger and materialized metrics path."""
    metrics_path_str = None if metrics_path is None else str(Path(metrics_path))
    if metrics_path_str is None:
        return None, None
    if logger is not None:
        return logger, metrics_path_str
    return JsonlLogger(metrics_path_str), metrics_path_str


def error_family(error: Exception | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, RateLimitError):
        return "rate_limit"
    if isinstance(error, SkipError):
        return "skip"
    if isinstance(error, FatalError):
        return "fatal"
    if isinstance(error, RetryableError):
        return "retryable"
    return "unknown"


def estimate_cost(provider: object, tokens_in: int, tokens_out: int) -> float:
    estimator = getattr(provider, "estimate_cost", None)
    if callable(estimator):
        try:
            return float(estimator(tokens_in, tokens_out))
        except Exception:  # pragma: no cover - defensive guard
            return 0.0
    return 0.0


def provider_model(provider: object, *, allow_private: bool = False) -> str | None:
    attrs = ["model"]
    if allow_private:
        attrs.append("_model")
    for attr in attrs:
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def _provider_name(provider: ProviderSPI | AsyncProviderSPI | None) -> str | None:
    if provider is None:
        return None
    name = getattr(provider, "name", None)
    if callable(name):
        return str(name())
    return None


def _request_hash(
    provider_name: str | None, request: ProviderRequest
) -> str | None:
    if provider_name is None:
        return None
    return content_hash(
        provider_name,
        request.prompt_text,
        request.options,
        request.max_tokens,
    )


def log_provider_skipped(
    event_logger: EventLogger | None,
    *,
    request_fingerprint: str,
    provider: ProviderSPI | AsyncProviderSPI,
    request: ProviderRequest,
    attempt: int,
    total_providers: int,
    error: SkipError,
) -> None:
    if event_logger is None:
        return
    provider_name = _provider_name(provider)
    event_logger.emit(
        "provider_skipped",
        {
            "request_fingerprint": request_fingerprint,
            "request_hash": _request_hash(provider_name, request),
            "provider": provider_name,
            "attempt": attempt,
            "total_providers": total_providers,
            "reason": getattr(error, "reason", None),
            "error_message": str(error),
        },
    )


def log_provider_call(
    event_logger: EventLogger | None,
    *,
    request_fingerprint: str,
    provider: ProviderSPI | AsyncProviderSPI,
    request: ProviderRequest,
    attempt: int,
    total_providers: int,
    status: str,
    latency_ms: int | None,
    tokens_in: int | None,
    tokens_out: int | None,
    error: Exception | None,
    metadata: Mapping[str, Any],
    shadow_used: bool,
    allow_private_model: bool = False,
) -> None:
    if event_logger is None:
        return

    provider_name = _provider_name(provider)
    event_logger.emit(
        "provider_call",
        {
            "request_fingerprint": request_fingerprint,
            "request_hash": _request_hash(provider_name, request),
            "provider": provider_name,
            "model": provider_model(provider, allow_private=allow_private_model),
            "attempt": attempt,
            "total_providers": total_providers,
            "status": status,
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "error_family": error_family(error),
            "shadow_used": shadow_used,
            "trace_id": metadata.get("trace_id"),
            "project_id": metadata.get("project_id"),
        },
    )


def log_run_metric(
    event_logger: EventLogger | None,
    *,
    request_fingerprint: str,
    request: ProviderRequest,
    provider: ProviderSPI | AsyncProviderSPI | None,
    status: str,
    attempts: int,
    latency_ms: int,
    tokens_in: int | None,
    tokens_out: int | None,
    cost_usd: float,
    error: Exception | None,
    metadata: Mapping[str, Any],
    shadow_used: bool,
) -> None:
    if event_logger is None:
        return

    provider_name = _provider_name(provider)
    event_logger.emit(
        "run_metric",
        {
            "request_fingerprint": request_fingerprint,
            "request_hash": _request_hash(provider_name, request),
            "provider": provider_name,
            "status": status,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": float(cost_usd),
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "error_family": error_family(error),
            "shadow_used": shadow_used,
            "trace_id": metadata.get("trace_id"),
            "project_id": metadata.get("project_id"),
        },
    )


__all__ = [
    "MetricsPath",
    "resolve_event_logger",
    "error_family",
    "estimate_cost",
    "provider_model",
    "log_provider_skipped",
    "log_provider_call",
    "log_run_metric",
]
