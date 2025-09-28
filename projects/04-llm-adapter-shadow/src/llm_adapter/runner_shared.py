"""Shared helpers for runner modules."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from threading import Lock
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable

from .errors import FatalError, RateLimitError, RetryableError, SkipError
from .observability import EventLogger, JsonlLogger
from .utils import content_hash

if TYPE_CHECKING:
    from .provider_spi import AsyncProviderSPI, ProviderRequest, ProviderSPI

MetricsPath = str | Path | None


class RateLimitReservation:
    def __init__(
        self,
        limiter: "TokenBucketRateLimiter",
        wait_time: float,
    ) -> None:
        self._limiter = limiter
        self._wait_time = wait_time
        self._done = False

    def wait_sync(self) -> None:
        if self._wait_time > 0:
            try:
                self._limiter.sleep(self._wait_time)
            except Exception:  # noqa: BLE001
                self.cancel()
                raise

    async def wait_async(self) -> None:
        if self._wait_time > 0:
            try:
                await self._limiter.async_sleep(self._wait_time)
            except Exception:  # noqa: BLE001
                self.cancel()
                raise

    def commit(self) -> None:
        self._done = True

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._limiter.release()


AsyncSleep = Callable[[float], Awaitable[None]]


class TokenBucketRateLimiter:
    def __init__(
        self,
        rpm: int,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        async_sleep: AsyncSleep | None = None,
    ) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self._clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.async_sleep: AsyncSleep = async_sleep or asyncio.sleep
        self._lock = Lock()
        self._interval = 60.0 / float(rpm)
        self._next_time = self._clock()

    def reserve(self) -> RateLimitReservation:
        with self._lock:
            now = self._clock()
            ready_at = max(self._next_time, now)
            wait_time = max(ready_at - now, 0.0)
            self._next_time = ready_at + self._interval
        return RateLimitReservation(self, wait_time)

    def release(self) -> None:
        with self._lock:
            self._next_time = max(self._clock(), self._next_time - self._interval)


def create_rate_limiter(rpm: int | None) -> TokenBucketRateLimiter | None:
    if rpm is None or rpm <= 0:
        return None
    return TokenBucketRateLimiter(rpm)


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
