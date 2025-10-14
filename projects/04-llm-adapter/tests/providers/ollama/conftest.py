from __future__ import annotations

from collections.abc import Callable, Sequence
import importlib
from pathlib import Path
from typing import Any

import pytest

from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.errors import RateLimitError, RetriableError


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

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def iter_lines(self):  # pragma: no cover - streaming未使用
        yield from self._chunks


def _load_ollama_module() -> Any:
    try:
        return importlib.import_module("adapter.core.providers.ollama")
    except ModuleNotFoundError as exc:  # pragma: no cover - RED 期待
        pytest.fail(f"ollama provider module is missing: {exc}")


@pytest.fixture
def ollama_module() -> Any:
    return _load_ollama_module()


@pytest.fixture
def provider_config_factory(tmp_path: Path) -> Callable[[str, str], ProviderConfig]:
    def factory(provider: str, model: str) -> ProviderConfig:
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

    return factory


@pytest.fixture
def fake_client_installer() -> Callable[[Any, str], pytest.MonkeyPatch]:
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
            self.pull_called = False

        def show(self, payload: dict[str, Any]) -> _FakeResponse:
            if self._mode == "missing_model":
                return _FakeResponse({}, status_code=404)
            return _FakeResponse({"result": "ok"})

        def pull(self, payload: dict[str, Any]) -> _FakeResponse:
            self.pull_called = True
            if self._mode == "missing_model":
                raise AssertionError("pull should not be called when auto pull is disabled")
            return _FakeResponse({"done": True})

        def chat(
            self,
            payload: dict[str, Any],
            *,
            timeout: float | None = None,
            stream: bool | None = None,
        ) -> _FakeResponse:
            if self._mode == "success":
                return _FakeResponse(
                    {
                        "message": {"content": "Hello from Ollama"},
                        "prompt_eval_count": 7,
                        "eval_count": 3,
                    }
                )
            if self._mode == "stream":
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
            if self._mode == "stream_chunks_only":
                chunks = [
                    b'{"message": {"content": "Hello"}}',
                    b'{"message": {"content": " from"}}',
                    b'{"message": {"content": " stream"}, "done": true, "done_reason": "stop"}',
                ]
                return _FakeResponse({}, chunks=chunks)
            if self._mode == "rate_limit":
                raise RateLimitError("too many requests")
            if self._mode == "server_error":
                raise RetriableError("temporary server error")
            raise AssertionError(f"unsupported mode: {self._mode}")

        def set_mode(self, mode: str) -> None:
            self._mode = mode

    def installer(module: Any, mode: str) -> pytest.MonkeyPatch:
        requests_exceptions = getattr(module, "requests_exceptions", None)
        if requests_exceptions is None:
            compat = importlib.import_module("adapter.core.providers._requests_compat")
            requests_exceptions = getattr(compat, "requests_exceptions", None)
        if requests_exceptions is None:  # pragma: no cover - RED 期待
            pytest.fail("ollama provider must expose requests_exceptions")

        def _init(self, **kwargs: Any) -> None:
            _FakeClient.__init__(self, **kwargs)
            self.set_mode(mode)

        client_cls = type(
            "_ConfiguredFakeClient",
            (_FakeClient,),
            {"__init__": _init},
        )
        local_patch = pytest.MonkeyPatch()
        local_patch.setattr(module, "create_session", lambda: object(), raising=False)
        local_patch.setattr(module, "OllamaClient", client_cls, raising=False)
        return local_patch

    return installer
