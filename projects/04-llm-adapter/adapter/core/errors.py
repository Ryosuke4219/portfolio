"""Normalized exception hierarchy for adapter core."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AdapterError(Exception):
    """Base class for adapter-originated errors."""


class RetryableError(AdapterError):
    """Base class for errors where retrying may succeed."""


class SkipError(AdapterError):
    """Base class for skip events."""


class FatalError(AdapterError):
    """Base class for unrecoverable errors."""


class TimeoutError(RetryableError):
    """Raised when a provider call exceeds the timeout."""


class RateLimitError(RetryableError):
    """Raised when a provider signals rate limiting."""


class AuthError(FatalError):
    """Raised when authentication fails."""


class RetriableError(RetryableError):
    """Raised for transient provider issues."""


class SkipReason(str, Enum):
    """Enumerates structured skip reasons."""

    UNKNOWN = "unknown"
    MISSING_GEMINI_API_KEY = "missing_gemini_api_key"
    MISSING_OPENROUTER_API_KEY = "missing_openrouter_api_key"
    MISSING_OLLAMA_ENDPOINT = "missing_ollama_endpoint"
    OLLAMA_OFFLINE = "ollama_offline"


class ProviderSkip(SkipError):
    """Raised when a provider should be skipped without counting as failure."""

    def __init__(
        self,
        message: str,
        *,
        reason: SkipReason | str | None = None,
    ) -> None:
        super().__init__(message)
        self._message = message
        if reason is None:
            self.reason: SkipReason | None = None
        elif isinstance(reason, SkipReason):
            self.reason = reason
        else:
            try:
                self.reason = SkipReason(reason)
            except ValueError:
                self.reason = SkipReason.UNKNOWN

    def __str__(self) -> str:
        return self._message


class ConfigError(FatalError):
    """Raised when provider configuration is invalid."""


@dataclass(slots=True, init=False)
class AllFailedError(FatalError):
    """Raised when all providers fail to produce a result."""

    message: str
    failures: list[Any]
    batch: Sequence[tuple[int, Any]] | None
    stop_reason: str | None

    def __init__(
        self,
        message: str,
        *,
        failures: Iterable[Any] | None = None,
        batch: Sequence[tuple[int, Any]] | None = None,
        stop_reason: str | None = None,
    ) -> None:
        Exception.__init__(self, message)
        self.message = message
        self.failures = list(failures) if failures is not None else []
        self.batch = list(batch) if batch is not None else None
        self.stop_reason = stop_reason


class ParallelExecutionError(FatalError):
    """Raised when a parallel execution encounters multiple failures."""

    def __init__(
        self,
        message: str,
        *,
        failures: Iterable[Any] | None = None,
        batch: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.failures = list(failures) if failures is not None else None
        self.batch = batch


__all__ = [
    "AdapterError",
    "RetryableError",
    "SkipError",
    "FatalError",
    "TimeoutError",
    "RateLimitError",
    "AuthError",
    "RetriableError",
    "ProviderSkip",
    "SkipReason",
    "ConfigError",
    "AllFailedError",
    "ParallelExecutionError",
]
