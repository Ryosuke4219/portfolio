"""Helpers for instantiating providers from configuration strings."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from ..provider_spi import ProviderSPI
from .gemini import GeminiProvider
from .mock import MockProvider
from .ollama import OllamaProvider

__all__ = [
    "parse_provider_spec",
    "create_provider_from_spec",
    "provider_from_environment",
]


ProviderFactory = Callable[[str], ProviderSPI]


def parse_provider_spec(spec: str) -> tuple[str, str]:
    """Split ``spec`` into ``(prefix, remainder)``.

    Only the first ``":"`` acts as the separator so that model identifiers such
    as ``"gemma3n:e2b"`` remain intact.
    """

    if not isinstance(spec, str):
        raise ValueError("provider spec must be a string")

    prefix, sep, remainder = spec.partition(":")
    if not sep:
        raise ValueError(f"invalid provider spec: {spec!r}")

    prefix = prefix.strip().lower()
    remainder = remainder.strip()
    if not prefix or not remainder:
        raise ValueError(f"invalid provider spec: {spec!r}")

    return prefix, remainder


def create_provider_from_spec(
    spec: str,
    *,
    factories: Mapping[str, ProviderFactory] | None = None,
) -> ProviderSPI:
    prefix, remainder = parse_provider_spec(spec)

    default_factories: dict[str, ProviderFactory] = {
        "gemini": lambda model: GeminiProvider(model=model),
        "ollama": lambda model: OllamaProvider(model=model),
        "mock": lambda model: MockProvider(model),
    }

    if factories:
        default_factories.update(factories)

    try:
        factory = default_factories[prefix]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"unsupported provider prefix: {prefix}") from exc

    return factory(remainder)


_DISABLED_VALUES = {"", "none", "null", "off"}


def provider_from_environment(
    variable: str,
    *,
    default: str | None = None,
    optional: bool = False,
    factories: Mapping[str, ProviderFactory] | None = None,
) -> ProviderSPI | None:
    value = os.environ.get(variable, default)
    if value is None:
        if optional:
            return None
        raise ValueError(f"environment variable {variable} is required")

    normalized = value.strip()
    if normalized.lower() in _DISABLED_VALUES:
        if optional:
            return None
        raise ValueError(
            f"environment variable {variable} disabled without optional flag"
        )

    return create_provider_from_spec(normalized, factories=factories)
