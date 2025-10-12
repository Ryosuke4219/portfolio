from __future__ import annotations

import pytest
from src.llm_adapter.providers.ollama import OllamaProvider

from tests.helpers.fakes import FakeSession


def test_ollama_provider_prefers_base_url_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://env-base")
    monkeypatch.setenv("OLLAMA_HOST", "http://legacy-host")
    provider = OllamaProvider(
        "test-model",
        session=FakeSession(),
        auto_pull=False,
    )

    assert provider._host == "http://env-base"


def test_ollama_provider_legacy_host_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://legacy-host")
    provider = OllamaProvider(
        "test-model",
        session=FakeSession(),
        auto_pull=False,
    )

    assert provider._host == "http://legacy-host"
