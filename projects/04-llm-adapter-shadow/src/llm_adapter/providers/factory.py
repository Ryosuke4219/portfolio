"""Helpers for instantiating providers from configuration strings."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import os

from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .base import BaseProvider
from .gemini import GeminiProvider
from .mock import MockProvider
from .ollama import OllamaProvider

__all__ = [
    "parse_provider_spec",
    "create_provider_from_spec",
    "provider_from_environment",
    "OpenAIProvider",
    "OpenRouterProvider",
]


ProviderFactory = Callable[[str], ProviderSPI]


class _ModelOnlyProvider(BaseProvider):
    def __init__(self, *, name: str, model: str) -> None:
        super().__init__(name=name, model=model)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        raise NotImplementedError(
            f"{self.name()} provider requires full implementation"
        )


class OpenAIProvider(_ModelOnlyProvider):
    def __init__(self, model: str) -> None:
        super().__init__(name="openai", model=model)


class OpenRouterProvider(_ModelOnlyProvider):
    def __init__(self, model: str) -> None:
        super().__init__(name="openrouter", model=model)


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
        "openai": lambda model: OpenAIProvider(model=model),
        "openrouter": lambda model: OpenRouterProvider(model=model),
        "ollama": lambda model: OllamaProvider(model=model),
        "mock": lambda model: MockProvider(model),
    }

    if factories:
        default_factories.update(factories)

    try:
        factory = default_factories[prefix]
    except KeyError as exc:  # pragma: no cover - defensive guard
        supported = ", ".join(sorted(default_factories))
        raise ValueError(
            f"unsupported provider prefix: {prefix}. supported: {supported}. "
            "OpenAI は無印、Gemini は google-genai を導入してください。"
        ) from exc

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
