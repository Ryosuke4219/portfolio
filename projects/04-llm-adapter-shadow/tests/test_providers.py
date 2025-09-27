from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest

from src.llm_adapter.errors import AuthError, ProviderSkip, RateLimitError, TimeoutError
from src.llm_adapter.provider_spi import (
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
    TokenUsage,
)
from src.llm_adapter.providers.factory import (
    create_provider_from_spec,
    parse_provider_spec,
    provider_from_environment,
)
from src.llm_adapter.providers.gemini import GeminiProvider
from src.llm_adapter.providers.ollama import OllamaProvider
from src.llm_adapter.providers import ollama as ollama_module


DEFAULT_MODEL = "test-model"


def test_parse_provider_spec_allows_colons_in_model():
    prefix, model = parse_provider_spec("ollama:gemma3n:e2b")
    assert prefix == "ollama"
    assert model == "gemma3n:e2b"


def test_parse_provider_spec_requires_separator():
    with pytest.raises(ValueError):
        parse_provider_spec("gemini")


def test_provider_request_builds_messages_from_prompt():
    request = ProviderRequest(model=DEFAULT_MODEL, prompt="  hello ")

    assert request.prompt_text == "hello"
    assert request.chat_messages == [{"role": "user", "content": "hello"}]
    assert request.stop is None


def test_provider_request_normalizes_messages_and_stop():
    request = ProviderRequest(
        model=DEFAULT_MODEL,
        prompt="",
        messages=[{"role": "User", "content": [" hi ", " there "]}],
        stop=[" END ", ""],
    )

    assert request.prompt_text == "hi"
    assert request.chat_messages == [{"role": "User", "content": ["hi", "there"]}]
    assert request.stop == ("END",)


def test_provider_response_populates_token_usage_from_inputs():
    response = ProviderResponse(text="ok", latency_ms=10, tokens_in=3, tokens_out=4)

    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 4
    assert response.input_tokens == 3
    assert response.output_tokens == 4


def test_provider_response_uses_token_usage_if_provided():
    usage = TokenUsage(prompt=5, completion=7)
    response = ProviderResponse(text="ok", latency_ms=10, token_usage=usage)

    assert response.tokens_in == 5
    assert response.tokens_out == 7
    assert response.token_usage is usage


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


def test_ollama_provider_prefers_base_url_over_legacy(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://env-base")
    monkeypatch.setenv("OLLAMA_HOST", "http://legacy-host")

    provider = OllamaProvider(
        "test-model",
        session=_FakeSession(),
        auto_pull=False,
    )

    assert provider._host == "http://env-base"


def test_ollama_provider_legacy_host_fallback(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://legacy-host")

    provider = OllamaProvider(
        "test-model",
        session=_FakeSession(),
        auto_pull=False,
    )

    assert provider._host == "http://legacy-host"


class _RecordClient:
    def __init__(self):
        self.calls = []

        class _Models:
            def __init__(self, outer):
                self._outer = outer

            def generate_content(self, **kwargs):
                config_obj = kwargs.get("config")
                if config_obj is not None:
                    to_dict = getattr(config_obj, "to_dict", None)
                    if callable(to_dict):
                        kwargs["_config_dict"] = to_dict()
                self._outer.calls.append(kwargs)
                return SimpleNamespace(
                    text="こんにちは",
                    usage_metadata=SimpleNamespace(input_tokens=12, output_tokens=7),
                )

        self.models = _Models(self)


def test_gemini_provider_invokes_client_with_config():
    client = _RecordClient()
    provider = GeminiProvider(
        "gemini-2.5-flash",
        client=client,  # type: ignore[arg-type]
        generation_config={"temperature": 0.2},
    )

    request = ProviderRequest(
        model="gemini-2.5-flash",
        prompt="テスト",
        max_tokens=128,
        metadata={"system": "you are helpful"},
        temperature=0.4,
        top_p=0.85,
        stop=["END"],
    )
    response = provider.invoke(request)

    assert response.text == "こんにちは"
    assert response.token_usage.prompt == 12
    assert response.token_usage.completion == 7
    assert response.latency_ms >= 0
    assert response.model == "gemini-2.5-flash"
    assert response.tokens_in == 12
    assert response.tokens_out == 7
    assert response.finish_reason is None
    assert response.raw is not None

    recorded = client.calls.pop()
    assert recorded["model"] == "gemini-2.5-flash"
    assert recorded["contents"][0]["role"] == "system"
    assert recorded["contents"][0]["parts"][0]["text"] == "you are helpful"
    assert recorded["contents"][1]["role"] == "user"
    recorded_config = recorded["config"]
    config_view: dict[str, Any] = {}
    config_dict = recorded.get("_config_dict")
    if isinstance(config_dict, Mapping):
        config_view.update(config_dict)
    to_dict = getattr(recorded_config, "to_dict", None)
    if callable(to_dict):
        maybe = to_dict()
        if isinstance(maybe, Mapping):
            config_view.update(maybe)
    if isinstance(recorded_config, Mapping):
        config_view.update(recorded_config)

    temperature = config_view.get("temperature")
    if temperature is None and hasattr(recorded_config, "temperature"):
        temperature = getattr(recorded_config, "temperature")
    max_tokens = config_view.get("max_output_tokens")
    if max_tokens is None and hasattr(recorded_config, "max_output_tokens"):
        max_tokens = getattr(recorded_config, "max_output_tokens")

    stop_sequences = config_view.get("stop_sequences")
    top_p = config_view.get("top_p")
    if top_p is None and hasattr(recorded_config, "top_p"):
        top_p = getattr(recorded_config, "top_p")
    if stop_sequences is None and hasattr(recorded_config, "stop_sequences"):
        stop_sequences = getattr(recorded_config, "stop_sequences")

    assert temperature == 0.2
    assert top_p == pytest.approx(0.85)
    assert stop_sequences == ["END"]
    assert max_tokens == 128
    assert isinstance(recorded["contents"], list)


def test_gemini_provider_uses_request_model_override_and_finish_reason():
    class _Client:
        def __init__(self):
            self.calls = []

            class _Models:
                def __init__(self, outer):
                    self._outer = outer

                def generate_content(self, **kwargs):
                    self._outer.calls.append(kwargs)
                    return SimpleNamespace(
                        text="ok",
                        usage_metadata=SimpleNamespace(input_tokens=2, output_tokens=3),
                        candidates=[SimpleNamespace(finish_reason="STOP")],
                    )

            self.models = _Models(self)

    client = _Client()
    provider = GeminiProvider("gemini-1.5-pro", client=client)  # type: ignore[arg-type]

    request = ProviderRequest(prompt="hello", model="gemini-1.5-pro-exp")
    response = provider.invoke(request)

    recorded = client.calls.pop()
    assert recorded["model"] == "gemini-1.5-pro-exp"
    assert response.model == "gemini-1.5-pro-exp"
    assert response.finish_reason == "STOP"
    assert response.tokens_in == 2
    assert response.tokens_out == 3


def test_gemini_provider_skips_without_api_key(monkeypatch):
    from src.llm_adapter.providers import gemini as gemini_module

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    stub_module = SimpleNamespace(Client=lambda **_: SimpleNamespace(models=None, responses=None))
    monkeypatch.setattr(gemini_module, "genai", stub_module, raising=False)

    provider = GeminiProvider("gemini-2.5-flash")

    with pytest.raises(ProviderSkip) as excinfo:
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))

    assert excinfo.value.reason == "missing_gemini_api_key"


def test_gemini_provider_translates_rate_limit():
    class _FailingModels:
        def generate_content(self, **kwargs):
            err = Exception("rate limited")
            setattr(err, "status", "RESOURCE_EXHAUSTED")
            raise err

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(RateLimitError):
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))


def test_gemini_provider_translates_rate_limit_status_object():
    class _StatusCode:
        def __init__(self, name: str):
            self.name = name

        def __str__(self) -> str:  # pragma: no cover - for defensive normalization
            return f"StatusCode.{self.name}"

    class _FailingModels:
        def generate_content(self, **kwargs):
            err = Exception("rate limited")
            setattr(err, "status", _StatusCode("RESOURCE_EXHAUSTED"))
            raise err

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(RateLimitError):
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))


def test_gemini_provider_preserves_rate_limit_error_instances():
    raised_error = RateLimitError("rate limited")

    class _FailingModels:
        def generate_content(self, **kwargs):
            raise raised_error

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(RateLimitError) as excinfo:
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))

    assert excinfo.value is raised_error


def test_gemini_provider_translates_timeout_status_object():
    class _StatusCode:
        def __init__(self, name: str):
            self.name = name

        def __str__(self) -> str:  # pragma: no cover - for defensive normalization
            return f"StatusCode.{self.name}"

    class _FailingModels:
        def generate_content(self, **kwargs):
            err = Exception("timeout")
            setattr(err, "code", _StatusCode("DEADLINE_EXCEEDED"))
            raise err

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))


def test_gemini_provider_preserves_timeout_error_instances():
    raised_error = TimeoutError("took too long")

    class _FailingModels:
        def generate_content(self, **kwargs):
            raise raised_error

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(TimeoutError) as excinfo:
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))

    assert excinfo.value is raised_error


@pytest.mark.parametrize(
    "code_name, expected",
    [
        ("RESOURCE_EXHAUSTED", RateLimitError),
        ("DEADLINE_EXCEEDED", TimeoutError),
    ],
)
def test_gemini_provider_translates_callable_code_status(
    code_name: str, expected: type[Exception]
):
    class _StatusCode:
        def __init__(self, name: str):
            self.name = name

        def __str__(self) -> str:  # pragma: no cover - for defensive normalization
            return f"StatusCode.{self.name}"

    class _ApiError(Exception):
        def __init__(self, name: str):
            super().__init__(f"{name.lower()}")
            self._status_code = _StatusCode(name)

        def code(self) -> _StatusCode:
            return self._status_code

    class _FailingModels:
        def __init__(self, error: Exception):
            self._error = error

        def generate_content(self, **kwargs):
            raise self._error

    class _Client:
        def __init__(self, error: Exception):
            self.models = _FailingModels(error)

    provider = GeminiProvider(
        "gemini-2.5-flash",
        client=_Client(_ApiError(code_name)),  # type: ignore[arg-type]
    )

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))


def test_gemini_provider_translates_named_timeout_exception():
    class Timeout(Exception):
        """Exception with a Timeout name similar to requests.exceptions.Timeout."""

    class _FailingModels:
        def generate_content(self, **kwargs):
            raise Timeout("network timeout")

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (429, RateLimitError),
        (401, AuthError),
        (403, AuthError),
        (408, TimeoutError),
        (504, TimeoutError),
    ],
)
def test_gemini_provider_translates_http_errors(status_code: int, expected: type[Exception]):
    class _HttpError(Exception):
        def __init__(self, code: int):
            super().__init__(f"http {code}")
            self.response = SimpleNamespace(status_code=code)

    class _FailingModels:
        def generate_content(self, **kwargs):
            raise _HttpError(status_code)

    class _Client:
        def __init__(self):
            self.models = _FailingModels()

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())  # type: ignore[arg-type]

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(model="gemini-2.5-flash", prompt="hello"))


def test_ollama_provider_auto_pull_and_chat():
    class Session(_FakeSession):
        def __init__(self):
            super().__init__()
            self._chat_called = False
            self.last_timeout = None
            self.last_payload: dict | None = None

        def post(self, url, json=None, stream=False, timeout=None):
            self.calls.append((url, json, stream))
            if url.endswith("/api/chat"):
                self.last_timeout = timeout
                self.last_payload = json
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
                        "done_reason": "stop",
                    },
                )
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    response = provider.invoke(ProviderRequest(model="gemma3n:e2b", prompt="hello"))

    assert response.text == "hello"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 5
    assert response.latency_ms >= 0
    assert response.model == "gemma3n:e2b"
    assert response.tokens_in == 3
    assert response.tokens_out == 5
    assert response.finish_reason == "stop"
    assert response.raw["message"]["content"] == "hello"
    assert session._chat_called
    assert session.last_timeout == provider._timeout
    assert session.last_payload is not None
    assert "REQUEST_TIMEOUT_S" not in session.last_payload
    assert "request_timeout_s" not in session.last_payload

    show_calls = [url for url, *_ in session.calls if url.endswith("/api/show")]
    assert len(show_calls) == 2  # first miss + verification after pull

    chat_payload = next(payload for url, payload, _ in session.calls if url.endswith("/api/chat"))
    assert chat_payload["model"] == "gemma3n:e2b"
    assert chat_payload["messages"] == [{"role": "user", "content": "hello"}]
    assert chat_payload["stream"] is False


def test_ollama_provider_merges_request_options():
    class Session(_FakeSession):
        def post(self, url, json=None, stream=False, timeout=None):
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                return _FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                return _FakeResponse(
                    status_code=200,
                    payload={
                        "message": {"content": "hi"},
                        "prompt_eval_count": 1,
                        "eval_count": 2,
                    },
                )
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3", session=session, host="http://localhost")

    request = ProviderRequest(
        model="gemma3",
        prompt="hi",
        max_tokens=32,
        temperature=0.4,
        top_p=0.9,
        stop=["END"],
        timeout_s=5.0,
        options={"options": {"stop": ["ALT"], "seed": 99}, "stream": True},
    )
    provider.invoke(request)

    chat_payload = next(payload for url, payload, _ in session.calls if url.endswith("/api/chat"))
    assert chat_payload["stream"] is True
    assert chat_payload["model"] == "gemma3"
    options_payload = chat_payload["options"]
    assert options_payload["num_predict"] == 32
    assert options_payload["temperature"] == pytest.approx(0.4)
    assert options_payload["top_p"] == pytest.approx(0.9)
    assert options_payload["stop"] == ["ALT"]
    assert options_payload["seed"] == 99


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (401, AuthError),
        (429, RateLimitError),
        (408, TimeoutError),
        (504, TimeoutError),
    ],
)
def test_ollama_provider_auto_pull_error_mapping(status_code: int, expected: type[Exception]):
    class Session(_FakeSession):
        def __init__(self):
            super().__init__()
            self.pull_response: _FakeResponse | None = None

        def post(self, url, json=None, stream=False, timeout=None):
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                self._show_calls += 1
                # First show indicates model missing, subsequent would succeed if we got that far.
                if self._show_calls == 1:
                    return _FakeResponse(status_code=404, payload={})
                return _FakeResponse(status_code=200, payload={})
            if url.endswith("/api/pull"):
                assert stream is True
                response = _FakeResponse(status_code=status_code, payload={})
                self.pull_response = response
                return response
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(model="gemma3n:e2b", prompt="hello"))

    assert session.pull_response is not None
    assert session.pull_response.closed


def test_ollama_provider_request_timeout_override():
    class Session(_FakeSession):
        def __init__(self):
            super().__init__()
            self.last_timeout = None
            self.last_payload: dict | None = None

        def post(self, url, json=None, stream=False, timeout=None):
            if url.endswith("/api/show"):
                return _FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                self.last_timeout = timeout
                self.last_payload = json
                return _FakeResponse(
                    status_code=200,
                    payload={"message": {"content": "ok"}},
                )
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    response = provider.invoke(
        ProviderRequest(
            model="gemma3n:e2b",
            prompt="hello",
            options={"REQUEST_TIMEOUT_S": "2.5", "extra": True},
        )
    )

    assert response.text == "ok"
    assert session.last_timeout == pytest.approx(2.5)
    assert session.last_payload is not None
    assert "REQUEST_TIMEOUT_S" not in session.last_payload
    assert "request_timeout_s" not in session.last_payload
    assert session.last_payload.get("extra") is True


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (401, AuthError),
        (504, TimeoutError),
    ],
)
def test_ollama_provider_maps_auth_error(status_code: int, expected: type[Exception]):
    class Session(_FakeSession):
        def __init__(self):
            super().__init__()
            self.last_chat_response: _FakeResponse | None = None

        def post(self, url, json=None, stream=False, timeout=None):
            if url.endswith("/api/show"):
                return _FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                response = _FakeResponse(status_code=status_code, payload={})
                self.last_chat_response = response
                return response
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(model="gemma3n:e2b", prompt="hello"))

    assert session.last_chat_response is not None
    assert session.last_chat_response.closed
