from __future__ import annotations

import pytest

from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory


# ストリームレスポンスがチャンク単位で結合されることを確認する。
def test_ollama_provider_streaming_concat(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
) -> None:
    module = ollama_module
    local_patch = fake_client_installer(module, "stream")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    try:
        config = provider_config_factory("ollama", "phi3")
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            prompt="say hello",
            options={"stream": True},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "Hello from stream"
    assert response.token_usage.prompt == 5
    assert response.token_usage.completion == 2


# イテレータがメッセージ本文のみを返す構成でも同等結果になることを保証する。
def test_ollama_provider_streaming_iter_lines_only(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
) -> None:
    module = ollama_module
    local_patch = fake_client_installer(module, "stream_chunks_only")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    try:
        config = provider_config_factory("ollama", "phi3")
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            prompt="say hello",
            options={"stream": True},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "Hello from stream"
    assert response.raw["message"]["content"] == "Hello from stream"
