"""Cost estimation helpers shared across runners."""
from __future__ import annotations

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
    if hasattr(provider, "estimate_cost"):
        estimator = provider.estimate_cost
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


__all__ = [
    "estimate_cost",
]
