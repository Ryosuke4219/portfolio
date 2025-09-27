"""Error hierarchy for the minimal LLM adapter.

Runner retry policy:
- ``RateLimitError`` → waits 0.05 seconds before continuing with the next provider.
- ``TimeoutError`` / ``RetriableError`` → immediately try the next provider with no delay.
- ``ProviderSkip`` → simply recorded as a skip event; control moves on without retrying. Reasons
  are tracked via :class:`SkipReason` when available.
"""

from __future__ import annotations

from enum import Enum


class AdapterError(Exception):
    """Base class for errors originating from providers or the adapter."""


class TimeoutError(AdapterError):
    """Raised when a provider does not respond within the expected window (instant fallback)."""


class RateLimitError(AdapterError):
    """Raised when a provider rejects the request due to rate limiting (0.05 s backoff)."""


class AuthError(AdapterError):
    """Raised when credentials are missing or invalid for the provider."""


class RetriableError(AdapterError):
    """Raised for transient issues where retrying with another provider may help.

    Runner instantly falls back to the next provider when this error is encountered.
    """


class FatalError(AdapterError):
    """Raised for unrecoverable issues that should halt the runner."""


class SkipReason(str, Enum):
    """Enumerates structured reasons for skipping a provider."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MISSING_GEMINI_API_KEY = "missing_gemini_api_key"


class ProviderSkip(AdapterError):
    """Raised when a provider should be skipped without counting as a failure (logged only)."""

    def __init__(
        self, message: str, *, reason: SkipReason | str | None = None
    ) -> None:
        super().__init__(message)
        if isinstance(reason, SkipReason):
            self.reason: SkipReason | str | None = reason
        elif isinstance(reason, str):
            try:
                self.reason = SkipReason(reason)
            except ValueError:
                self.reason = reason
        else:
            self.reason = None


class ConfigError(AdapterError):
    """Raised when a provider is misconfigured."""


__all__ = [
    "AdapterError",
    "TimeoutError",
    "RateLimitError",
    "AuthError",
    "RetriableError",
    "FatalError",
    "SkipReason",
    "ProviderSkip",
    "ConfigError",
]
