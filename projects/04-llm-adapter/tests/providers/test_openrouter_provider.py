# ruff: noqa: B009, B010
from __future__ import annotations

from collections.abc import Callable
import importlib
from pathlib import Path
from typing import Any

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.errors import AuthError, ProviderSkip, RateLimitError, RetriableError, SkipReason
from adapter.core.provider_spi import ProviderRequest
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
    session_calls = getattr(session, "calls", [])
    assert session_calls
    url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None


def test_openrouter_provider_resolves_api_key_from_env_mapping_when_auth_env_is_custom(
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
                        "message": {"role": "assistant", "content": "custom mapping"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_AUTH_ENV", raising=False)
    monkeypatch.setenv("MAPPED_CUSTOM_AUTH_ENV", "mapped-custom-value")
    try:
        config = _provider_config(tmp_path)
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
    url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None


def test_openrouter_provider_allows_literal_env_mapping_value(
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
                        "message": {"role": "assistant", "content": "literal"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        config = _provider_config(tmp_path)
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
    url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and payload.get("stream") is None


def test_openrouter_provider_uses_request_option_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert payload is not None
        assert "api_key" not in payload
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "inline option"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider: Any | None = None
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            prompt="option auth",
            options={"api_key": "inline-secret"},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert provider is not None
    session = getattr(provider, "_session")
    headers = getattr(session, "headers", {})
    assert headers.get("Authorization") == "Bearer inline-secret"
    assert response.text == "inline option"
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream, _timeout = session_calls[0]
    assert stream is False
    assert payload is not None and "api_key" not in payload


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
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    url, _payload, stream, _timeout = session_calls[0]
    assert url == f"{base_url}/chat/completions"
    assert stream is False


def test_openrouter_provider_prefers_env_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()
    base_url = "https://mapped.example/openrouter"

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
                        "message": {"role": "assistant", "content": "mapped"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setenv("CUSTOM_MAPPED_API_KEY", "mapped-key")
    monkeypatch.setenv("CUSTOM_MAPPED_BASE_URL", base_url)
    try:
        config = _provider_config(tmp_path)
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


def test_openrouter_provider_env_mapping_accepts_literal_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert stream is False
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "literal api key"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        config = _provider_config(tmp_path)
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


def test_openrouter_provider_env_mapping_accepts_literal_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()
    base_url = "https://example.invalid"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert url == f"{base_url}/chat/completions"
        assert stream is False
        assert timeout == pytest.approx(2.5)
        assert payload is not None
        assert "request_timeout_s" not in payload
        assert "REQUEST_TIMEOUT_S" not in payload
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "literal"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    try:
        config = _provider_config(tmp_path)
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
    module = _load_openrouter_module()
    literal_url = "https://literal.example/api/v1"
    env_url = "https://env.example/api/v1"

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert url == f"{literal_url}/chat/completions"
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "literal override"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", env_url)
    try:
        config = _provider_config(tmp_path)
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


def test_openrouter_provider_supports_streaming(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert stream is True
        assert payload is not None
        assert payload.get("stream") is True
        return _FakeResponse(
            {},
            lines=[
                b"data: {\"choices\": [{\"delta\": {\"content\": \"hel\"}}]}",
                b"data: {\"choices\": [{\"delta\": {\"content\": \"lo\"}, \"finish_reason\": \"stop\"}], \"usage\": {\"prompt_tokens\": 3, \"completion_tokens\": 2}, \"model\": \"stream-model\"}",
                b"data: [DONE]",
            ],
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        request = ProviderRequest(model=config.model, messages=[], options={"stream": True})
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "hello"
    assert response.finish_reason == "stop"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 2
    assert response.model == "stream-model"
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream_flag, _timeout = session_calls[0]
    assert stream_flag is True
    assert payload is not None and payload.get("stream") is True


def test_openrouter_provider_request_options_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert stream is False
        assert payload is not None
        # config.temperature < raw option < request override
        assert payload.get("temperature") == pytest.approx(0.7)
        assert payload.get("response_format") == "json_schema"
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "overridden"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        config.temperature = 0.2
        config.raw["options"] = {"temperature": 0.7, "response_format": "json_schema"}
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "override options")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "overridden"


def test_openrouter_provider_request_options_take_priority_over_config_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()
    captured: dict[str, Any] = {}

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> _FakeResponse:
        assert stream is False
        assert payload is not None
        captured["payload"] = payload
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "priority"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                "model": "priority-model",
            }
        )

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        config.raw["options"] = {"response_format": "config", "seed": 42}
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            messages=[],
            options={"response_format": "request", "extra": "value"},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "priority"
    payload = captured.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("response_format") == "request"
    assert payload.get("extra") == "value"
    assert payload.get("seed") == 42


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


def test_openrouter_provider_normalizes_auth_error_from_request_exception(
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
        error = requests_exceptions.RequestException("forbidden")
        response = _FakeResponse({}, status_code=403)
        setattr(error, "response", response)
        raise error

    local_patch = _install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = _provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "403 RequestException")
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
    assert result.error.reason == SkipReason.MISSING_OPENROUTER_API_KEY
    assert result.backoff_next_provider is True


def test_openrouter_provider_skip_message_mentions_custom_auth_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_openrouter_module()
    local_patch = _install_fake_session(module, lambda *_: _FakeResponse({}))
    monkeypatch.delenv("CUSTOM_ROUTER_KEY", raising=False)
    try:
        config = _provider_config(tmp_path)
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
    module = _load_openrouter_module()
    local_patch = _install_fake_session(module, lambda *_: _FakeResponse({}))
    monkeypatch.delenv("CUSTOM_ROUTER_KEY", raising=False)
    monkeypatch.delenv("MAPPED_ROUTER_KEY", raising=False)
    try:
        config = _provider_config(tmp_path)
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
