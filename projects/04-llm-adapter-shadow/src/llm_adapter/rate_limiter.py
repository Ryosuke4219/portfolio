"""Rate limiting utilities shared across runner modules."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import threading
import time


class RateLimiter:
    """Simple monotonic-rate limiter supporting sync/async acquisition."""

    def __init__(
        self,
        rpm: int,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        async_sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be greater than zero")
        self._rate_per_second = float(rpm) / 60.0
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._async_sleep = async_sleep or asyncio.sleep
        self._capacity = 1.0
        self._tokens = self._capacity
        self._updated_at = self._clock()
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated_at
        if elapsed > 0.0:
            self._tokens = min(
                self._capacity, self._tokens + elapsed * self._rate_per_second
            )
            self._updated_at = now

    def _reserve(self, now: float) -> float:
        self._refill(now)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        deficit = 1.0 - self._tokens
        wait = deficit / self._rate_per_second
        self._tokens = 0.0
        self._updated_at = now
        return wait

    def acquire(self) -> None:
        while True:
            with self._lock:
                wait = self._reserve(self._clock())
            if wait <= 0.0:
                return
            self._sleep(wait)

    async def acquire_async(self) -> None:
        while True:
            async with self._async_lock:
                wait = self._reserve(self._clock())
            if wait <= 0.0:
                return
            await self._async_sleep(wait)


def resolve_rate_limiter(
    rpm: int | None,
    *,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    async_sleep: Callable[[float], Awaitable[None]] | None = None,
) -> RateLimiter | None:
    if rpm is None:
        return None
    return RateLimiter(rpm, clock=clock, sleep=sleep, async_sleep=async_sleep)


__all__ = ["RateLimiter", "resolve_rate_limiter", "time", "asyncio", "threading"]

