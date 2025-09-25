"""Error hierarchy for the minimal LLM adapter."""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for errors originating from providers or the adapter."""


class TimeoutError(AdapterError):
    """Raised when a provider does not respond within the expected window."""


class RateLimitError(AdapterError):
    """Raised when a provider rejects the request due to rate limiting."""


class AuthError(AdapterError):
    """Raised when credentials are missing or invalid for the provider."""


class RetriableError(AdapterError):
    """Raised for transient issues where retrying with another provider may help."""


class FatalError(AdapterError):
    """Raised for unrecoverable issues that should halt the runner."""


class ProviderSkip(AdapterError):
    """Raised when a provider should be skipped without counting as a failure."""

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class ConfigError(AdapterError):
    """Raised when a provider is misconfigured."""


__all__ = [
    "AdapterError",
    "TimeoutError",
    "RateLimitError",
    "AuthError",
    "RetriableError",
    "FatalError",
    "ProviderSkip",
    "ConfigError",
]
