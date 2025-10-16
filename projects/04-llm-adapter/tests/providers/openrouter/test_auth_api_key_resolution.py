# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.providers import ProviderFactory
from tests.providers.openrouter.conftest import (
    install_fake_session,
    load_openrouter_module,
    provider_config,
    single_choice_responder,
)


def test_openrouter_provider_resolves_api_key_from_auth_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    responder = single_choice_responder("auth", expected_stream=False)
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
    responder = single_choice_responder("custom mapping", expected_stream=False)
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
    responder = single_choice_responder("literal", expected_stream=False)
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
    responder = single_choice_responder("literal api key", expected_stream=False)
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
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None
