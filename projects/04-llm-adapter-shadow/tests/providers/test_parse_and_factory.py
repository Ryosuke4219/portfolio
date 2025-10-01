from __future__ import annotations

import pytest

from src.llm_adapter.provider_spi import ProviderSPI
from src.llm_adapter.providers import factory as providers_factory


class DummyProvider(ProviderSPI):
    def __init__(self, model: str):
        self._model = model

    def name(self) -> str:  # pragma: no cover - trivial
        return f"dummy:{self._model}"

    def capabilities(self) -> set[str]:  # pragma: no cover - trivial
        return {"chat"}

    def invoke(self, request):  # pragma: no cover - unused in tests
        raise NotImplementedError


def test_parse_provider_spec_allows_colons_in_model():
    prefix, model = providers_factory.parse_provider_spec("ollama:gemma3n:e2b")
    assert prefix == "ollama"
    assert model == "gemma3n:e2b"


def test_parse_provider_spec_requires_separator():
    with pytest.raises(ValueError):
        providers_factory.parse_provider_spec("gemini")


def test_create_provider_from_spec_supports_overrides():
    provider = providers_factory.create_provider_from_spec(
        "gemini:test-model",
        factories={"gemini": lambda model: DummyProvider(model)},
    )
    assert isinstance(provider, DummyProvider)
    assert provider.name() == "dummy:test-model"


def test_create_provider_from_spec_supports_openai():
    provider = providers_factory.create_provider_from_spec("openai:gpt-4o-mini")
    assert provider.__class__.__name__ == "OpenAIProvider"


def test_create_provider_from_spec_supports_openrouter():
    provider = providers_factory.create_provider_from_spec(
        "openrouter:meta/llama3.1-8b-instruct"
    )
    assert provider.__class__.__name__ == "OpenRouterProvider"


def test_provider_from_environment_optional_none(monkeypatch):
    monkeypatch.setenv("SHADOW_PROVIDER", "none")
    result = providers_factory.provider_from_environment(
        "SHADOW_PROVIDER",
        optional=True,
        factories={"gemini": lambda model: DummyProvider(model)},
    )
    assert result is None


def test_provider_from_environment_disabled_requires_optional(monkeypatch):
    monkeypatch.setenv("PRIMARY_PROVIDER", "none")
    with pytest.raises(ValueError):
        providers_factory.provider_from_environment(
            "PRIMARY_PROVIDER",
            optional=False,
            factories={"gemini": lambda model: DummyProvider(model)},
        )


def test_create_provider_from_spec_unsupported_prefix_error_message():
    with pytest.raises(ValueError) as exc_info:
        providers_factory.create_provider_from_spec("invalid:demo")

    message = str(exc_info.value)
    assert message.startswith("unsupported provider prefix: invalid. supported: ")
    assert message.endswith(
        ". OpenAI は無印、Gemini は google-genai を導入してください。"
    )
