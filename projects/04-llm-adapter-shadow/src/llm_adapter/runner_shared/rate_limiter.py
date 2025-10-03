"""Rate limiter utilities and provider metadata helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .. import rate_limiter as _rate_limiter

if TYPE_CHECKING:
    from ..provider_spi import AsyncProviderSPI, ProviderSPI

RateLimiter = _rate_limiter.RateLimiter
resolve_rate_limiter = _rate_limiter.resolve_rate_limiter
time = _rate_limiter.time
asyncio = _rate_limiter.asyncio
threading = _rate_limiter.threading


def provider_model(
    provider: ProviderSPI | AsyncProviderSPI | object,
    *,
    allow_private: bool = False,
) -> str | None:
    """Return the model identifier exposed by the provider if available."""
    attrs = ["model"]
    if allow_private:
        attrs.append("_model")
    for attr in attrs:
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "RateLimiter",
    "resolve_rate_limiter",
    "time",
    "asyncio",
    "threading",
    "provider_model",
]
