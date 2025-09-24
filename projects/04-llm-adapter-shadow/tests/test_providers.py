from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.llm_adapter.errors import AuthError, RateLimitError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderSPI
from src.llm_adapter.providers.factory import (
    create_provider_from_spec,
    parse_provider_spec,
    provider_from_environment,
)
from src.llm_adapter.providers.gemini import GeminiProvider
from src.llm_adapter.providers.ollama import OllamaProvider
from src.llm_adapter.providers import ollama as ollama_module


def test_parse_provider_spec_allows_colons_in_model():
    prefix, model = parse_provider_spec("ollama:gemma3n:e2b")
    assert prefix == "ollama"
    assert model == "gemma3n:e2b"


def test_parse_provider_spec_requires_separator():
    with pytest.raises(ValueError):
        parse_provider_spec("gemini")


class DummyProvider(ProviderSPI):
    def __init__(self, model: str):
        self._model = model

    def name(self) -> str:  # pragma: no cover - trivial
        return f"dummy:{self._model}"

    def capabilities(self) -> set[str]:  # pragma: no cover - trivial
        return {"chat"}

    def invoke(self, request: ProviderRequest):  # pragma: no cover - unused
        raise NotImplementedError


def test_create_provider_from_spec_supports_overrides():
    provider = create_provider_from_spec(
        "gemini:test-model",
        factories={"gemini": lambda model: DummyProvider(model)},
    )
    assert isinstance(provider, DummyProvider)
    assert provider.name() == "dummy:test-model"


def test_provider_from_environment_optional_none(monkeypatch):
    monkeypatch.setenv("SHADOW_PROVIDER", "none")
    result = provider_from_environment(
        "SHADOW_PROVIDER",
        optional=True,
        factories={"gemini": lambda model: DummyProvider(model)},
    )
    assert result is None


def test_provider_from_environment_disabled_requires_optional(monkeypatch):
    monkeypatch.setenv("PRIMARY_PROVIDER", "none")
    with pytest.raises(ValueError):
        provider_from_environment(
            "PRIMARY_PROVIDER",
            optional=False,
            factories={"gemini": lambda model: DummyProvider(model)},
        )


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict | None = None, lines: list[bytes] | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = lines or [b"{}"]
        self.closed = False

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise ollama_module.requests_exceptions.HTTPError(response=self)

    def json(self):
        return self._payload

    def iter_lines(self):
        yield from self._lines

    def close(self):
        self.closed = True

    def __enter__(self):  # pragma: no cover - context protocol
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - context protocol
        self.close()
        return False


class _FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict | None, bool]] = []
        self._show_calls = 0

    def post(self, url, json=None, stream=False, timeout=None):  # pragma: no cover - patched in tests
        raise NotImplementedError


class _RecordClient:
    def __init__(self):
        self.calls = []

        class _Responses:
            def __init__(self, outer):
                self._outer = outer

            def generate(self, **kwargs):
                self._outer.calls.append(kwargs)
                return SimpleNamespace(
                    output_text="こんにちは",
                    usage_metadata=SimpleNamespace(input_tokens=12, output_tokens=7),
                )

        self.responses = _Responses(self)


def test_gemini_provider_invokes_client_with_config():
    client = _RecordClient()
    provider = GeminiProvider(
        "gemini-2.5-flash",
        client=client,  # type: ignore[arg-type]
        generation_config={"temperature": 0.2},
    )

    request = ProviderRequest(
        prompt="テスト", max_tokens=128, options={"system": "you are helpful"}
    )
    response = provider.invoke(request)

    assert response.text == "こんにちは"
    assert response.token_usage.prompt == 12
    assert response.token_usage.completion == 7
    assert response.latency_ms >= 0

    recorded = client.calls.pop()
    assert recorded["model"] == "gemini-2.5-flash"
    assert recorded["config"]["temperature"] == 0.2
    assert recorded["config"]["max_output_tokens"] == 128
    assert isinstance(recorded["input"], list)


def test_gemini_provider_translates_rate_limit():
    class _FailingResponses:
        def generate(self, **kwargs):
            err = Exception("rate limited")
            setattr(err, "status", "RESOURCE_EXHAUSTED")
            raise err

    class _Client:
        def __init__(self):
            self.responses = _FailingResponses()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(RateLimitError):
        provider.invoke(ProviderRequest(prompt="hello"))


def test_ollama_provider_auto_pull_and_chat():
    class Session(_FakeSession):
        def __init__(self):
            super().__init__()
            self._chat_called = False

        def post(self, url, json=None, stream=False, timeout=None):
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                self._show_calls += 1
                if self._show_calls == 1:
                    return _FakeResponse(status_code=404, payload={})
                return _FakeResponse(status_code=200, payload={})
            if url.endswith("/api/pull"):
                return _FakeResponse(status_code=200, payload={}, lines=[b"{}"])
            if url.endswith("/api/chat"):
                self._chat_called = True
                return _FakeResponse(
                    status_code=200,
                    payload={
                        "message": {"content": "hello"},
                        "prompt_eval_count": 3,
                        "eval_count": 5,
                    },
                )
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    response = provider.invoke(ProviderRequest(prompt="hello"))

    assert response.text == "hello"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 5
    assert response.latency_ms >= 0
    assert session._chat_called

    show_calls = [url for url, *_ in session.calls if url.endswith("/api/show")]
    assert len(show_calls) == 2  # first miss + verification after pull


def test_ollama_provider_maps_auth_error():
    class Session(_FakeSession):
        def post(self, url, json=None, stream=False, timeout=None):
            if url.endswith("/api/show"):
                return _FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                return _FakeResponse(status_code=401, payload={})
            raise AssertionError(f"unexpected url: {url}")

    provider = OllamaProvider("gemma3n:e2b", session=Session(), host="http://localhost")

    with pytest.raises(AuthError):
        provider.invoke(ProviderRequest(prompt="hello"))
