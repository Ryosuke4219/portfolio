"""Error hierarchy for the minimal LLM adapter.

Runner retry policy:
- ``RateLimitError`` → waits 0.05 seconds before continuing with the next provider.
- ``TimeoutError`` / ``RetriableError`` → immediately try the next provider with no delay.
- ``ProviderSkip`` → simply recorded as a skip event; control moves on without retrying.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum


class AdapterError(Exception):
    """Base class for errors originating from providers or the adapter."""


class RetryableError(AdapterError):
    """Base class for errors where retrying the next provider is recommended."""


class SkipError(AdapterError):
    """Base class for events where the provider should be skipped without retry."""


class FatalError(AdapterError):
    """Base class for unrecoverable issues that should halt the runner."""


class AllFailedError(FatalError):
    """Raised when all providers fail without yielding a usable response."""

    def __init__(self, message: str, *, failures: Sequence[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.failures: list[dict[str, str]] = list(failures or [])


class ParallelExecutionError(FatalError):
    """Raised when all parallel workers fail to produce a response."""

    def __init__(
        self,
        message: str,
        *,
        failures: Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        if failures is None:
            self.failures: list[dict[str, str]] | None = None
        else:
            self.failures = [dict(detail) for detail in failures]


class TimeoutError(RetryableError):
    """Raised when a provider does not respond within the expected window (instant fallback)."""


class RateLimitError(RetryableError):
    """Raised when a provider rejects the request due to rate limiting (0.05 s backoff)."""


class AuthError(FatalError):
    """Raised when credentials are missing or invalid for the provider."""


class RetriableError(RetryableError):
    """Raised for transient issues where retrying with another provider may help.

    Runner instantly falls back to the next provider when this error is encountered.
    """


class SkipReason(str, Enum):
    """Structured reasons explaining why a provider was skipped."""

    UNKNOWN = "unknown"
    MISSING_GEMINI_API_KEY = "missing_gemini_api_key"
    MISSING_OPENROUTER_API_KEY = "missing_openrouter_api_key"


class ProviderSkip(SkipError):
    """Raised when a provider should be skipped without counting as a failure (logged only)."""

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
    """Raised when a provider is misconfigured."""


__all__ = [
    "AdapterError",
    "RetriableError",
    "RetryableError",
    "TimeoutError",
    "RateLimitError",
    "AuthError",
    "SkipError",
    "FatalError",
    "AllFailedError",
    "ParallelExecutionError",
    "ProviderSkip",
    "SkipReason",
    "ConfigError",
]
