# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.errors import ProviderSkip, SkipReason
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory
from tests.providers.openrouter.conftest import (
    FakeResponse,
    install_fake_session,
    load_openrouter_module,
    provider_config,
)


def test_openrouter_provider_resolves_api_key_from_auth_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "auth"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CUSTOM_OPENROUTER_KEY", "custom-value")
    try:
        config = provider_config(tmp_path)
        config.auth_env = "CUSTOM_OPENROUTER_KEY"
        provider = ProviderFactory.create(config)
        session = getattr(provider, "_session")
        headers = getattr(session, "headers", {})
        assert headers.get("Authorization") == "Bearer custom-value"
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "auth env")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "auth"
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None



def test_openrouter_provider_resolves_api_key_from_env_mapping_when_auth_env_is_custom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "custom mapping"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_AUTH_ENV", raising=False)
    monkeypatch.setenv("MAPPED_CUSTOM_AUTH_ENV", "mapped-custom-value")
    try:
        config = provider_config(tmp_path)
        config.auth_env = "CUSTOM_AUTH_ENV"
        config.raw["env"] = {"CUSTOM_AUTH_ENV": "MAPPED_CUSTOM_AUTH_ENV"}
        provider = ProviderFactory.create(config)
        session = getattr(provider, "_session")
        headers = getattr(session, "headers", {})
        assert headers.get("Authorization") == "Bearer mapped-custom-value"
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "custom auth env mapping")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "custom mapping"
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None


def test_openrouter_provider_allows_literal_env_mapping_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        config = provider_config(tmp_path)
        config.raw.setdefault("env", {})
        config.raw["env"]["OPENROUTER_API_KEY"] = "sk-inline"
        provider = ProviderFactory.create(config)
        session = getattr(provider, "_session")
        headers = getattr(session, "headers", {})
        assert headers.get("Authorization") == "Bearer sk-inline"
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "literal inline")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "literal"
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None


def test_openrouter_provider_env_mapping_accepts_literal_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is False
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "literal api key"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        config = provider_config(tmp_path)
        config.raw["env"] = {"OPENROUTER_API_KEY": "sk-inline"}
        provider = ProviderFactory.create(config)
        session = getattr(provider, "_session")
        headers = getattr(session, "headers", {})
        assert headers.get("Authorization") == "Bearer sk-inline"
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "literal api key")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "literal api key"


def test_openrouter_provider_uses_request_option_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert payload is not None
        assert "api_key" not in payload
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "inline option"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    internal_keys = getattr(module, "_INTERNAL_OPTION_KEYS")
    restored_internal_key = "api_key" in internal_keys
    internal_keys.discard("api_key")
    provider: Any | None = None
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            prompt="option auth",
            options={"api_key": "inline-secret"},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()
        if restored_internal_key:
            internal_keys.add("api_key")

    assert provider is not None
    session = getattr(provider, "_session")
    headers = getattr(session, "headers", {})
    assert headers.get("Authorization") == "Bearer inline-secret"
    assert response.text == "inline option"


def test_openrouter_provider_request_options_override_env_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert payload is not None
        assert "api_key" not in payload
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "override"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-secret")
    provider: Any | None = None
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        session = getattr(provider, "_session")
        headers = getattr(session, "headers", {})
        assert headers.get("Authorization") == "Bearer env-secret"
        request = ProviderRequest(
            model=config.model,
            prompt="inline override",
            options={"api_key": "inline-secret"},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert provider is not None
    session = getattr(provider, "_session")
    headers = getattr(session, "headers", {})
    assert headers.get("Authorization") == "Bearer inline-secret"
    assert response.text == "override"
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and "api_key" not in payload


def test_openrouter_provider_skip_without_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    local_patch = install_fake_session(module, lambda *_: FakeResponse({}))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hi")
    finally:
        local_patch.undo()

    assert result.status == "skip"
    assert result.failure_kind == "skip"
    assert isinstance(result.error, ProviderSkip)
    assert result.error.reason == SkipReason.MISSING_OPENROUTER_API_KEY
    assert result.backoff_next_provider is True


def test_openrouter_provider_skip_message_mentions_custom_auth_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    local_patch = install_fake_session(module, lambda *_: FakeResponse({}))
    monkeypatch.delenv("CUSTOM_ROUTER_KEY", raising=False)
    try:
        config = provider_config(tmp_path)
        config.auth_env = "CUSTOM_ROUTER_KEY"
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "missing key")
    finally:
        local_patch.undo()

    assert result.status == "skip"
    assert isinstance(result.error, ProviderSkip)
    assert "CUSTOM_ROUTER_KEY" in str(result.error)


def test_openrouter_provider_skip_message_mentions_configured_and_resolved_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    local_patch = install_fake_session(module, lambda *_: FakeResponse({}))
    monkeypatch.delenv("CUSTOM_ROUTER_KEY", raising=False)
    monkeypatch.delenv("MAPPED_ROUTER_KEY", raising=False)
    try:
        config = provider_config(tmp_path)
        config.auth_env = "CUSTOM_ROUTER_KEY"
        config.raw["env"] = {"CUSTOM_ROUTER_KEY": "MAPPED_ROUTER_KEY"}
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "missing key")
    finally:
        local_patch.undo()

    assert result.status == "skip"
    assert isinstance(result.error, ProviderSkip)
    message = str(result.error)
    assert "CUSTOM_ROUTER_KEY" in message
    assert "MAPPED_ROUTER_KEY" in message
