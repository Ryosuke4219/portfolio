"""Cost estimation helpers shared across runners."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..provider_spi import AsyncProviderSPI, ProviderSPI

_COST_CACHE_ATTR = "_llm_adapter_cost_cache"


def _get_cached_cost(provider: object, tokens_in: int, tokens_out: int) -> float | None:
    try:
        cached_tokens, cached_value = getattr(provider, _COST_CACHE_ATTR)
    except AttributeError:
        return None
    except Exception:  # pragma: no cover - defensive guard
        return None
    if cached_tokens == (tokens_in, tokens_out):
        try:
            return float(cached_value)
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            return None
    return None


def estimate_cost(provider: object, tokens_in: int, tokens_out: int) -> float:
    cached = _get_cached_cost(provider, tokens_in, tokens_out)
    if cached is not None:
        return cached
    estimator = getattr(provider, "estimate_cost", None)
    if callable(estimator):
        try:
            value = float(estimator(tokens_in, tokens_out))
        except Exception:  # pragma: no cover - defensive guard
            return 0.0
        try:
            setattr(provider, _COST_CACHE_ATTR, ((tokens_in, tokens_out), value))
        except Exception:  # pragma: no cover - defensive guard
            pass
        return value
    return 0.0


def provider_model(
    provider: ProviderSPI | AsyncProviderSPI | None, *, allow_private: bool = False
) -> str | None:
    if provider is None:
        return None
    attrs = ["model"]
    if allow_private:
        attrs.append("_model")
    for attr in attrs:
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = ["estimate_cost", "provider_model"]
