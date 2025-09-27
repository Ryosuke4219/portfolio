"""Error hierarchy for the minimal LLM adapter.

Runner retry policy:
- ``RateLimitError`` → waits 0.05 seconds before continuing with the next provider.
- ``TimeoutError`` / ``RetryableError`` → immediately try the next provider with no delay.
- ``SkipError`` → simply recorded as a skip event; control moves on without retrying.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for errors originating from providers or the adapter."""


class RetryableError(AdapterError):
    """Base class for recoverable issues that should fall back to other providers."""


class RetriableError(RetryableError):
    """Backward-compatible alias for :class:`RetryableError`."""


class TimeoutError(RetryableError):
    """Raised when a provider does not respond within the expected window (instant fallback)."""


class RateLimitError(RetryableError):
    """Raised when a provider rejects the request due to rate limiting (backoff required)."""


class AuthError(AdapterError):
    """Raised when credentials are missing or invalid for the provider."""


class FatalError(AdapterError):
    """Raised for unrecoverable issues that should halt the runner."""


class SkipError(AdapterError):
    """Raised when a provider should be skipped without counting as a failure (logged only)."""


class ProviderSkip(SkipError):
    """Backward-compatible alias for :class:`SkipError`."""

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class ConfigError(AdapterError):
    """Raised when a provider is misconfigured."""


__all__ = [
    "AdapterError",
    "RetryableError",
    "TimeoutError",
    "RateLimitError",
    "AuthError",
    "RetriableError",
    "FatalError",
    "SkipError",
    "ProviderSkip",
    "ConfigError",
]
