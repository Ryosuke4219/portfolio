"""Token bucket helper utilities for runner orchestration."""

from __future__ import annotations

import asyncio
import time
from threading import Lock
from typing import Callable

from .runner_config import RunnerConfig

__all__ = [
    "TokenPermit",
    "TokenBucket",
    "token_bucket_from_config",
]


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
