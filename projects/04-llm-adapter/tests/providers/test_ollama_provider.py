from __future__ import annotations

from collections.abc import Sequence
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
from adapter.core.errors import ProviderSkip, RateLimitError, RetriableError, SkipReason
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status_code: int = 200,
        chunks: Sequence[bytes | str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.closed = False
        self._chunks: tuple[bytes | str, ...] = tuple(chunks or ())

    def json(self) -> dict[str, Any]:
        return self._payload

    def close(self) -> None:
        self.closed = True

    def iter_lines(self):  # pragma: no cover - streaming未使用
        yield from self._chunks


def _load_ollama_module() -> Any:
    try:
        return importlib.import_module("adapter.core.providers.ollama")
    except ModuleNotFoundError as exc:  # pragma: no cover - RED 期待
        pytest.fail(f"ollama provider module is missing: {exc}")


def _provider_config(tmp_path: Path, *, provider: str, model: str) -> ProviderConfig:
    config_path = tmp_path / f"{provider}.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider=provider,
        endpoint=None,
        model=model,
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
        timeout_s=30,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def _install_fake_client(module: Any, mode: str) -> pytest.MonkeyPatch:
    requests_exceptions = getattr(module, "requests_exceptions", None)
    if requests_exceptions is None:
        compat = importlib.import_module("adapter.core.providers._requests_compat")
        requests_exceptions = getattr(compat, "requests_exceptions", None)
    if requests_exceptions is None:  # pragma: no cover - RED 期待
        pytest.fail("ollama provider must expose requests_exceptions")

    class _FakeClient:
        def __init__(
            self,
            *,
            host: str,
            session: Any,
            timeout: float,
            pull_timeout: float,
        ) -> None:
            self.host = host
            self.session = session
            self.timeout = timeout
            self.pull_timeout = pull_timeout

        def show(self, payload: dict[str, Any]) -> _FakeResponse:
            return _FakeResponse({"result": "ok"})

        def pull(self, payload: dict[str, Any]) -> _FakeResponse:
            return _FakeResponse({"done": True})

        def chat(
            self,
            payload: dict[str, Any],
            *,
            timeout: float | None = None,
            stream: bool | None = None,
        ) -> _FakeResponse:
            if mode == "success":
                return _FakeResponse(
                    {
                        "message": {"content": "Hello from Ollama"},
                        "prompt_eval_count": 7,
                        "eval_count": 3,
                    }
                )
            if mode == "stream":
                chunks = [
                    b'{"message": {"content": "Hello"}}',
                    b'{"message": {"content": " from"}}',
                    (
                        b'{"message": {"content": " stream"}, "done": true, '
                        b'"done_reason": "stop", "prompt_eval_count": 5, "eval_count": 2}'
                    ),
                ]
                return _FakeResponse(
                    {
                        "message": {"content": " stream"},
                        "done": True,
                        "done_reason": "stop",
                        "prompt_eval_count": 5,
                        "eval_count": 2,
                    },
                    chunks=chunks,
                )
            if mode == "rate_limit":
                raise RateLimitError("too many requests")
            if mode == "server_error":
                raise RetriableError("temporary server error")
            raise AssertionError(f"unsupported mode: {mode}")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(module, "create_session", lambda: object(), raising=False)
    monkeypatch.setattr(module, "OllamaClient", _FakeClient, raising=False)
    return monkeypatch


def test_ollama_provider_executor_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="success")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
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

    assert result.status == "ok"
    assert result.failure_kind is None
    assert result.response.text == "Hello from Ollama"
    assert result.response.token_usage.prompt == 7
    assert result.response.token_usage.completion == 3


def test_ollama_provider_streaming_concat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="stream")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
        config.raw["client"] = module.OllamaClient(
            host="http://127.0.0.1:11434",
            session=object(),
            timeout=60.0,
            pull_timeout=300.0,
        )
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            prompt="say hello",
            options={"stream": True},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "Hello from stream"
    assert response.token_usage.prompt == 5
    assert response.token_usage.completion == 2
    assert isinstance(response.raw, dict)
    assert response.raw.get("done") is True
    message_raw = response.raw.get("message") if isinstance(response.raw, dict) else None
    if isinstance(message_raw, dict):
        assert message_raw.get("content") == "Hello from stream"
    else:  # pragma: no cover - RED 期待
        pytest.fail("message payload must be a dict for streaming responses")


def test_ollama_provider_executor_success_in_ci(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="success")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    monkeypatch.setenv("CI", "true")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
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

    assert result.status == "ok"
    assert result.failure_kind is None
    assert result.response.text == "Hello from Ollama"
    assert result.response.token_usage.prompt == 7
    assert result.response.token_usage.completion == 3


@pytest.mark.parametrize("offline_value", ["0", "false"])
def test_ollama_provider_executor_success_in_ci_offline_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, offline_value: str
) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="success")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", offline_value)
    monkeypatch.setenv("CI", "true")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
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

    assert result.status == "ok"
    assert result.failure_kind is None
    assert result.response.text == "Hello from Ollama"
    assert result.response.token_usage.prompt == 7
    assert result.response.token_usage.completion == 3


def test_ollama_provider_rate_limit_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="rate_limit")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger rate limit")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "rate_limit"
    assert isinstance(result.error, RateLimitError)
    assert result.backoff_next_provider is True


def test_ollama_provider_server_error_normalized(tmp_path: Path) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="server_error")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "trigger server error")
    finally:
        local_patch.undo()

    assert result.status == "error"
    assert result.failure_kind == "retryable"
    assert isinstance(result.error, RetriableError)
    assert result.backoff_next_provider is False


def test_ollama_provider_skip_when_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="success")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "1")
    monkeypatch.delenv("CI", raising=False)
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hello")
    finally:
        local_patch.undo()

    assert result.status == "skip"
    assert result.failure_kind == "skip"
    assert isinstance(result.error, ProviderSkip)
    assert result.error.reason is SkipReason.OLLAMA_OFFLINE
    assert result.backoff_next_provider is True


def test_ollama_provider_skip_reason_in_ci_when_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="success")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "1")
    monkeypatch.setenv("CI", "true")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hello")
    finally:
        local_patch.undo()

    assert result.status == "skip"
    assert result.failure_kind == "skip"
    assert isinstance(result.error, ProviderSkip)
    assert result.error.reason is SkipReason.OLLAMA_OFFLINE
    assert result.backoff_next_provider is True


def test_ollama_provider_honors_offline_override_in_ci(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_ollama_module()
    local_patch = _install_fake_client(module, mode="success")
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "0")
    monkeypatch.setenv("CI", "true")
    try:
        config = _provider_config(tmp_path, provider="ollama", model="phi3")
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "say hello")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.failure_kind is None
    assert result.response.text == "Hello from Ollama"
