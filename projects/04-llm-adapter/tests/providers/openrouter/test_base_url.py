# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.providers import ProviderFactory

from tests.providers.openrouter.conftest import (
    FakeResponse,
    install_fake_session,
    load_openrouter_module,
    provider_config,
)


def test_openrouter_provider_executor_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url == "https://mock.openrouter.test/api/v1/chat/completions"
        assert stream is False
        assert payload is not None
        assert payload["model"] == "meta-llama/llama-3-8b-instruct:free"
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 5},
                "model": "meta-llama/llama-3-8b-instruct:free",
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hi")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.failure_kind is None
    assert result.response.text == "Hello"
    assert result.response.token_usage.prompt == 9
    assert result.response.token_usage.completion == 5
    assert result.response.finish_reason == "stop"


def test_openrouter_provider_resolves_base_url_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    base_url = "https://example.invalid/openrouter"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url == f"{base_url}/chat/completions"
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "env"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CUSTOM_BASE_URL", base_url)
    try:
        config = provider_config(tmp_path)
        config.raw["base_url_env"] = "CUSTOM_BASE_URL"
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "base url env")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "env"
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    url, _payload, stream, _timeout = session_calls[0]
    assert url == f"{base_url}/chat/completions"
    assert stream is False


def test_openrouter_provider_prefers_env_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    base_url = "https://mapped.example/openrouter"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url == f"{base_url}/chat/completions"
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "mapped"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setenv("CUSTOM_MAPPED_API_KEY", "mapped-key")
    monkeypatch.setenv("CUSTOM_MAPPED_BASE_URL", base_url)
    try:
        config = provider_config(tmp_path)
        config.raw["env"] = {
            "OPENROUTER_API_KEY": "CUSTOM_MAPPED_API_KEY",
            "OPENROUTER_BASE_URL": "CUSTOM_MAPPED_BASE_URL",
        }
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "env mapping")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "mapped"
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    url, _payload, stream, _timeout = session_calls[0]
    assert url == f"{base_url}/chat/completions"
    assert stream is False
    headers = getattr(session, "headers", {})
    assert headers.get("Authorization") == "Bearer mapped-key"


def test_openrouter_provider_env_mapping_accepts_literal_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    base_url = "https://example.invalid"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url == f"{base_url}/chat/completions"
        assert stream is False
        assert timeout == pytest.approx(2.5)
        assert payload is not None
        assert "request_timeout_s" not in payload
        assert "REQUEST_TIMEOUT_S" not in payload
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "literal"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    try:
        config = provider_config(tmp_path)
        config.raw["env"] = {"OPENROUTER_BASE_URL": base_url}
        config.raw["options"] = {"request_timeout_s": 2.5}
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "literal url")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "literal"
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    url, _payload, stream, timeout = session_calls[0]
    assert url == f"{base_url}/chat/completions"
    assert stream is False
    assert timeout == pytest.approx(2.5)


def test_openrouter_provider_env_mapping_literal_overrides_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    literal_url = "https://literal.example/api/v1"
    env_url = "https://env.example/api/v1"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url == f"{literal_url}/chat/completions"
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "literal override"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", env_url)
    try:
        config = provider_config(tmp_path)
        config.raw["env"] = {"OPENROUTER_BASE_URL": literal_url}
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "literal override")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "literal override"
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    url, _payload, stream, _timeout = session_calls[0]
    assert url == f"{literal_url}/chat/completions"
    assert stream is False
