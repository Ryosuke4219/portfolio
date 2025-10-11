from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.errors import AuthError, ProviderSkip, RateLimitError, RetriableError
from adapter.core.providers import ProviderFactory


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200, lines: list[bytes] | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.closed = False
        self._lines = list(lines or [])

    def json(self) -> dict[str, Any]:
        return self._payload

    def iter_lines(self):
        yield from self._lines

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _load_openrouter_module() -> Any:
    try:
        return importlib.import_module("adapter.core.providers.openrouter")
    except ModuleNotFoundError as exc:  # pragma: no cover - RED 期待
        pytest.fail(f"openrouter provider module is missing: {exc}")


def _provider_config(tmp_path: Path) -> ProviderConfig:
    config_path = tmp_path / "openrouter.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider="openrouter",
        endpoint="https://mock.openrouter.test/api/v1",
        model="meta-llama/llama-3-8b-instruct:free",
        auth_env="OPENROUTER_API_KEY",
        seed=0,
        temperature=0.2,
        top_p=0.9,
        max_tokens=256,
        timeout_s=15,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def _install_fake_session(module: Any, responder: Callable[[str, dict[str, Any] | None, bool, float | None], _FakeResponse]) -> pytest.MonkeyPatch:
    class _Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any] | None, bool, float | None]] = []
            self._headers: dict[str, str] = {}

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> _FakeResponse:
            self.calls.append((url, json, stream, timeout))
            return responder(url, json, stream, timeout)

        @property
        def headers(self) -> dict[str, str]:  # pragma: no cover - mutate via provider
            return self._headers

    monkeypatch = pytest.MonkeyPatch()
    session = _Session()
    monkeypatch.setattr(module, "create_session", lambda: session, raising=False)
    return monkeypatch


def test_openrouter_provider_executor_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert url == "https://mock.openrouter.test/api/v1/chat/completions"
        assert stream is False
        assert payload is not None
        assert payload["model"] == "meta-llama/llama-3-8b-instruct:free"
        return _FakeResponse(
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

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
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


def test_openrouter_provider_normalizes_rate_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        error = requests_exceptions.HTTPError("rate limit")
        response = _FakeResponse({}, status_code=429)
        setattr(error, "response", response)
        raise error

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger 429")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "rate_limit"
    assert isinstance(result.error, RateLimitError)
    assert result.backoff_next_provider is True


def test_openrouter_provider_normalizes_server_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        error = requests_exceptions.HTTPError("server error")
        response = _FakeResponse({}, status_code=503)
        setattr(error, "response", response)
        raise error

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger 503")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "retryable"
    assert isinstance(result.error, RetriableError)
    assert result.backoff_next_provider is False


def test_openrouter_provider_resolves_api_key_from_auth_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "auth"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CUSTOM_OPENROUTER_KEY", "custom-value")
    try:
        config = _provider_config(tmp_path)
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


def test_openrouter_provider_resolves_base_url_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()
    base_url = "https://example.invalid/openrouter"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert url == f"{base_url}/chat/completions"
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "env"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CUSTOM_BASE_URL", base_url)
    try:
        config = _provider_config(tmp_path)
        config.raw["base_url_env"] = "CUSTOM_BASE_URL"
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "base url env")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "env"


def test_openrouter_provider_normalizes_auth_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("openrouter provider must expose requests_exceptions")

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        error = requests_exceptions.HTTPError("unauthorized")
        response = _FakeResponse({}, status_code=401)
        setattr(error, "response", response)
        raise error

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "401")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "auth"
    assert isinstance(result.error, AuthError)
    assert result.backoff_next_provider is True


def test_openrouter_provider_skip_without_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_openrouter_module()
    local_patch = _install_fake_session(module, lambda *_: _FakeResponse({}))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hi")
    finally:
        local_patch.undo()

    assert result.status == "skip"
    assert result.failure_kind == "skip"
    assert isinstance(result.error, ProviderSkip)
    assert result.backoff_next_provider is True
