from __future__ import annotations

from collections.abc import Mapping

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.errors import ProviderSkip, SkipReason
from adapter.core.providers import ProviderFactory

_SUCCESS_ENV_CASES: tuple[Mapping[str, str], ...] = (
    {"LLM_ADAPTER_OFFLINE": "0"},
    {"LLM_ADAPTER_OFFLINE": "0", "CI": "true"},
    {"LLM_ADAPTER_OFFLINE": "false", "CI": "true"},
)

_SKIP_ENV_CASES: tuple[Mapping[str, str], ...] = (
    {"LLM_ADAPTER_OFFLINE": "1"},
    {"LLM_ADAPTER_OFFLINE": "1", "CI": "true"},
)


def _execute_with_env(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
    *,
    env: Mapping[str, str],
    attach_client: bool,
):
    module = ollama_module
    local_patch = fake_client_installer(module, "success")
    for key in ("LLM_ADAPTER_OFFLINE", "CI"):
        monkeypatch.delenv(key, raising=False)
    try:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        config = provider_config_factory("ollama", "phi3")
        if attach_client:
            config.raw["client"] = module.OllamaClient(
                host="http://127.0.0.1:11434",
                session=object(),
                timeout=60.0,
                pull_timeout=300.0,
            )
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hello")
    finally:
        local_patch.undo()
    return result


# 成功パス: 環境変数がオンライン運用を許可する場合は
# 既存クライアントを利用して通常応答を返す。
@pytest.mark.parametrize("env", _SUCCESS_ENV_CASES)
def test_ollama_provider_executor_success_cases(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
    env: Mapping[str, str],
) -> None:
    result = _execute_with_env(
        monkeypatch,
        provider_config_factory,
        fake_client_installer,
        ollama_module,
        env=env,
        attach_client=True,
    )

    assert result.status == "ok"
    assert result.failure_kind is None
    assert result.response.text == "Hello from Ollama"
    assert result.response.token_usage.prompt == 7
    assert result.response.token_usage.completion == 3


# スキップパス: 明示的にオフライン指定された場合は
# ProviderSkip を返し次プロバイダへフォールバックする。
@pytest.mark.parametrize("env", _SKIP_ENV_CASES)
def test_ollama_provider_skip_cases(
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory,
    fake_client_installer,
    ollama_module,
    env: Mapping[str, str],
) -> None:
    result = _execute_with_env(
        monkeypatch,
        provider_config_factory,
        fake_client_installer,
        ollama_module,
        env=env,
        attach_client=False,
    )

    assert result.status == "skip"
    assert result.failure_kind == "skip"
    assert isinstance(result.error, ProviderSkip)
    assert result.error.reason is SkipReason.OLLAMA_OFFLINE
    assert result.backoff_next_provider is True
