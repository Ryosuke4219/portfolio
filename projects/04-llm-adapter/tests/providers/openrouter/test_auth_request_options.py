# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory
from tests.providers.openrouter.conftest import (
    install_fake_session,
    load_openrouter_module,
    provider_config,
    single_choice_responder,
)


def test_openrouter_provider_uses_request_option_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    responder = single_choice_responder(
        "inline option",
        expected_stream=False,
        ensure_no_api_key=True,
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
    responder = single_choice_responder(
        "override",
        expected_stream=False,
        ensure_no_api_key=True,
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
