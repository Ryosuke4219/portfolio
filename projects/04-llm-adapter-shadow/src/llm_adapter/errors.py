"""Error hierarchy for the minimal LLM adapter.

Runner retry policy:
- ``RateLimitError`` → waits 0.05 seconds before continuing with the next provider.
- ``TimeoutError`` / ``RetriableError`` → immediately try the next provider with no delay.
- ``ProviderSkip`` → simply recorded as a skip event; control moves on without retrying.
"""

from __future__ import annotations

from enum import StrEnum


class AdapterError(Exception):
    """Base class for errors originating from providers or the adapter."""


class RetryableError(AdapterError):
    """Raised for transient issues where retrying with another provider may help."""


class SkipError(AdapterError):
    """Raised when a provider should be skipped without counting as a failure."""


class FatalError(AdapterError):
    """Raised for unrecoverable issues that should halt the runner."""


class TimeoutError(RetryableError):
    """Raised when a provider does not respond within the expected window (instant fallback)."""


class RateLimitError(RetryableError):
    """Raised when a provider rejects the request due to rate limiting (0.05 s backoff)."""


class RetriableError(RetryableError):
    """Backward-compatible alias for :class:`RetryableError`."""


class AuthError(AdapterError):
    """Raised when credentials are missing or invalid for the provider."""


class ProviderSkipReason(StrEnum):
    """Enumerates structured reasons for skipping providers."""

    UNSPECIFIED = "unspecified"
    MISSING_GEMINI_API_KEY = "missing_gemini_api_key"


class ProviderSkip(SkipError):
    """Raised when a provider should be skipped without counting as a failure (logged only)."""

    def __init__(
        self,
        message: str,
        *,
        reason: ProviderSkipReason | str | None = None,
    ) -> None:
        super().__init__(message)
        if reason is None:
            self.reason: ProviderSkipReason | None = None
        elif isinstance(reason, ProviderSkipReason):
            self.reason = reason
        else:
            try:
                self.reason = ProviderSkipReason(reason)
            except ValueError:
                self.reason = ProviderSkipReason.UNSPECIFIED

    def __str__(self) -> str:
        return super().__str__()


class ConfigError(AdapterError):
    """Raised when a provider is misconfigured."""


__all__ = [
    "AdapterError",
    "RetryableError",
    "SkipError",
    "FatalError",
    "TimeoutError",
    "RateLimitError",
    "RetriableError",
    "AuthError",
    "ProviderSkipReason",
    "ProviderSkip",
    "ConfigError",
]
