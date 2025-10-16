# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.errors import ProviderSkip, SkipReason
from adapter.core.providers import ProviderFactory
from tests.providers.openrouter.conftest import (
    FakeResponse,
    install_fake_session,
    load_openrouter_module,
    provider_config,
)


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
