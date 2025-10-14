from __future__ import annotations

import pytest

from llm_adapter.provider_spi import ProviderSPI
from llm_adapter.providers import factory as providers_factory


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


def test_create_provider_from_spec_supports_openrouter(monkeypatch):
    sentinel = DummyProvider("stub")

    def fake_openrouter(model: str):
        assert model == "meta-llama"
        return sentinel

    monkeypatch.setattr(providers_factory, "OpenRouterProvider", fake_openrouter)
    provider = providers_factory.create_provider_from_spec("openrouter:meta-llama")
    assert provider is sentinel


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
