# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.errors import AuthError, RateLimitError, RetriableError
from adapter.core.providers import ProviderFactory

from tests.providers.openrouter.conftest import (
    FakeResponse,
    install_fake_session,
    load_openrouter_module,
    provider_config,
)


def test_openrouter_provider_normalizes_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        error = requests_exceptions.HTTPError("rate limit")
        response = FakeResponse({}, status_code=429)
        setattr(error, "response", response)
        raise error

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger 429")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "rate_limit"
    assert isinstance(result.error, RateLimitError)
    assert result.backoff_next_provider is True


def test_openrouter_provider_normalizes_server_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        error = requests_exceptions.HTTPError("server error")
        response = FakeResponse({}, status_code=503)
        setattr(error, "response", response)
        raise error

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger 503")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "retryable"
    assert isinstance(result.error, RetriableError)
    assert result.backoff_next_provider is False


def test_openrouter_provider_normalizes_auth_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        error = requests_exceptions.HTTPError("unauthorized")
        response = FakeResponse({}, status_code=401)
        setattr(error, "response", response)
        raise error

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "401")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "auth"
    assert isinstance(result.error, AuthError)
    assert result.backoff_next_provider is True


def test_openrouter_provider_normalizes_auth_error_from_request_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        error = requests_exceptions.RequestException("forbidden")
        response = FakeResponse({}, status_code=403)
        setattr(error, "response", response)
        raise error

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "403 RequestException")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "auth"
    assert isinstance(result.error, AuthError)
    assert result.backoff_next_provider is True
