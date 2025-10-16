from __future__ import annotations

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.errors import RateLimitError, RetriableError
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory


# 自動 pull を無効化した場合はモデル不足を即時リトライエラーとして扱う。
def test_ollama_provider_auto_pull_disabled(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
) -> None:
    module = ollama_module
    local_patch = fake_client_installer(module, "missing_model")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    monkeypatch.setenv("OLLAMA_AUTO_PULL", "false")
    try:
        config = provider_config_factory("ollama", "phi3")
        provider = ProviderFactory.create(config)
        request = ProviderRequest(model=config.model, prompt="say hello")
        with pytest.raises(RetriableError):
            provider.invoke(request)
    finally:
        local_patch.undo()

    fake_client = provider._client
    assert getattr(fake_client, "pull_called", False) is False


# config.raw に auto_pull=True が設定されても環境変数で無効化されることを確認する。
def test_ollama_provider_auto_pull_disabled_env_override(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
) -> None:
    module = ollama_module
    local_patch = fake_client_installer(module, "missing_model")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    monkeypatch.setenv("OLLAMA_AUTO_PULL", "false")
    try:
        config = provider_config_factory("ollama", "phi3")
        config.raw["auto_pull"] = True
        provider = ProviderFactory.create(config)
        request = ProviderRequest(model=config.model, prompt="say hello")
        with pytest.raises(RetriableError):
            provider.invoke(request)
    finally:
        local_patch.undo()

    assert provider._auto_pull is False
    fake_client = provider._client
    assert getattr(fake_client, "pull_called", False) is False


# Ollama の 429 応答を RateLimitError に正規化する。
def test_ollama_provider_rate_limit_normalized(
    provider_config_factory,
    fake_client_installer,
    ollama_module,
) -> None:
    module = ollama_module
    local_patch = fake_client_installer(module, "rate_limit")
    try:
        config = provider_config_factory("ollama", "phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger rate limit")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "rate_limit"
    assert isinstance(result.error, RateLimitError)
    assert result.backoff_next_provider is True


# 5xx 応答は RetriableError として扱い次プロバイダを待機しない。
def test_ollama_provider_server_error_normalized(
    provider_config_factory,
    fake_client_installer,
    ollama_module,
) -> None:
    module = ollama_module
    local_patch = fake_client_installer(module, "server_error")
    try:
        config = provider_config_factory("ollama", "phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger server error")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "retryable"
    assert isinstance(result.error, RetriableError)
    assert result.backoff_next_provider is False
