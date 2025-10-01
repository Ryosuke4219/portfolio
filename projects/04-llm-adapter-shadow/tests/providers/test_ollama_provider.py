from __future__ import annotations

from typing import Any

# Third-party imports
import pytest

# First-party imports
from src.llm_adapter.errors import AuthError, RateLimitError, TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.ollama import OllamaProvider
from tests.helpers.fakes import FakeResponse, FakeSession


def test_ollama_provider_prefers_base_url_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://env-base")
    monkeypatch.setenv("OLLAMA_HOST", "http://legacy-host")
    provider = OllamaProvider(
        "test-model",
        session=FakeSession(),
        auto_pull=False,
    )

    assert provider._host == "http://env-base"


def test_ollama_provider_legacy_host_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://legacy-host")
    provider = OllamaProvider(
        "test-model",
        session=FakeSession(),
        auto_pull=False,
    )

    assert provider._host == "http://legacy-host"


def test_ollama_provider_auto_pull_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self._chat_called = False
            self.last_timeout: float | None = None
            self.last_payload: dict[str, Any] | None = None

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                self._show_calls += 1
                if self._show_calls == 1:
                    return FakeResponse(status_code=404, payload={})
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/pull"):
                return FakeResponse(status_code=200, payload={}, lines=[b"{}"])
            if url.endswith("/api/chat"):
                self.last_timeout = timeout
                self.last_payload = json
                self._chat_called = True
                return FakeResponse(
                    status_code=200,
                    payload={
                        "message": {"content": "hello"},
                        "prompt_eval_count": 3,
                        "eval_count": 5,
                        "done_reason": "stop",
                    },
                )
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setenv("OLLAMA_AUTO_PULL", "0")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    response = provider.invoke(ProviderRequest(prompt="hello", model="gemma3n:e2b"))

    assert response.text == "hello"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 5
    assert response.latency_ms >= 0
    assert response.model == "gemma3n:e2b"
    assert response.tokens_in == 3
    assert response.tokens_out == 5
    assert response.finish_reason == "stop"
    raw = response.raw
    assert isinstance(raw, dict)
    assert raw["message"]["content"] == "hello"
    assert session._chat_called
    assert session.last_timeout == pytest.approx(30.0)
    assert session.last_payload is not None
    last_payload = session.last_payload
    assert "REQUEST_TIMEOUT_S" not in last_payload
    assert "request_timeout_s" not in last_payload

    show_calls = [url for url, *_ in session.calls if url.endswith("/api/show")]
    assert len(show_calls) == 2

    chat_payload = next(
        payload for url, payload, _ in session.calls if url.endswith("/api/chat")
    )
    assert chat_payload is not None
    assert chat_payload["model"] == "gemma3n:e2b"
    assert chat_payload["messages"] == [{"role": "user", "content": "hello"}]
    assert chat_payload["stream"] is False


def test_ollama_provider_merges_request_options() -> None:
    class Session(FakeSession):
        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                return FakeResponse(
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
        prompt="hi",
        max_tokens=32,
        temperature=0.4,
        top_p=0.9,
        stop=("END",),
        timeout_s=5.0,
        options={"options": {"stop": ["ALT"], "seed": 99}, "stream": True},
        model="gemma3",
    )
    provider.invoke(request)

    chat_payload = next(
        payload for url, payload, _ in session.calls if url.endswith("/api/chat")
    )
    assert chat_payload is not None
    assert chat_payload["stream"] is True
    assert session.last_stream is True
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
def test_ollama_provider_auto_pull_error_mapping(
    status_code: int, expected: type[Exception], provider_request_model: str
) -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.pull_response: FakeResponse | None = None

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                self._show_calls += 1
                if self._show_calls == 1:
                    return FakeResponse(status_code=404, payload={})
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/pull"):
                assert stream is True
                response = FakeResponse(status_code=status_code, payload={})
                self.pull_response = response
                return response
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(prompt="hello", model="gemma3n:e2b"))

    assert session.pull_response is not None
    assert session.pull_response.closed


def test_ollama_provider_request_timeout_override() -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.last_timeout: float | None = None
            self.last_payload: dict[str, Any] | None = None

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            if url.endswith("/api/show"):
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                self.last_timeout = timeout
                self.last_payload = json
                return FakeResponse(
                    status_code=200,
                    payload={"message": {"content": "ok"}},
                )
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    response = provider.invoke(
        ProviderRequest(
            prompt="hello",
            timeout_s=None,
            options={"REQUEST_TIMEOUT_S": "2.5", "extra": True},
            model="gemma3n:e2b",
        )
    )

    assert response.text == "ok"
    assert session.last_timeout == pytest.approx(2.5)
    assert session.last_payload is not None
    last_payload = session.last_payload
    assert "REQUEST_TIMEOUT_S" not in last_payload
    assert "request_timeout_s" not in last_payload
    assert last_payload.get("extra") is True


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (401, AuthError),
        (504, TimeoutError),
    ],
)
def test_ollama_provider_maps_auth_error(
    status_code: int, expected: type[Exception]
) -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.last_chat_response: FakeResponse | None = None

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            if url.endswith("/api/show"):
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                response = FakeResponse(status_code=status_code, payload={})
                self.last_chat_response = response
                return response
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(prompt="hello", model="gemma3n:e2b"))

    assert session.last_chat_response is not None
    assert session.last_chat_response.closed
