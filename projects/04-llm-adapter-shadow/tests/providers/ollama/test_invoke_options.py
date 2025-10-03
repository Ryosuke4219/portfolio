from __future__ import annotations

from typing import Any

import pytest

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.ollama import OllamaProvider
from tests.helpers.fakes import FakeResponse

from .conftest import BaseChatSession


class SuccessfulAutoPullSession(BaseChatSession):
    def __init__(self) -> None:
        super().__init__()
        self._chat_called = False

    def handle_show(self) -> FakeResponse:
        self._show_calls += 1
        if self._show_calls == 1:
            return FakeResponse(status_code=404, payload={})
        return FakeResponse(status_code=200, payload={})

    def handle_pull(self, *, stream: bool) -> FakeResponse:
        assert stream is True
        return FakeResponse(status_code=200, payload={}, lines=[b"{}"])

    def handle_chat(
        self,
        *,
        json: dict[str, Any] | None,
        timeout: float | None,
        stream: bool,
    ) -> FakeResponse:
        self._chat_called = True
        assert stream is False
        return FakeResponse(
            status_code=200,
            payload={
                "message": {"content": "hello"},
                "prompt_eval_count": 3,
                "eval_count": 5,
                "done_reason": "stop",
            },
        )


class MergeOptionsSession(BaseChatSession):
    def handle_chat(
        self,
        *,
        json: dict[str, Any] | None,
        timeout: float | None,
        stream: bool,
    ) -> FakeResponse:
        assert json is not None
        return FakeResponse(
            status_code=200,
            payload={
                "message": {"content": "hi"},
                "prompt_eval_count": 1,
                "eval_count": 2,
            },
        )


class TimeoutOverrideSession(BaseChatSession):
    def handle_chat(
        self,
        *,
        json: dict[str, Any] | None,
        timeout: float | None,
        stream: bool,
    ) -> FakeResponse:
        return FakeResponse(status_code=200, payload={"message": {"content": "ok"}})


def test_ollama_provider_auto_pull_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_AUTO_PULL", "0")

    session = SuccessfulAutoPullSession()
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

    chat_call = next(
        call for call in session.calls if call[0].endswith("/api/chat")
    )
    chat_payload = chat_call[1]
    assert chat_payload is not None
    assert chat_payload["model"] == "gemma3n:e2b"
    assert chat_payload["messages"] == [{"role": "user", "content": "hello"}]
    assert "stream" not in chat_payload
    assert chat_call[2] is False


def test_ollama_provider_merges_request_options() -> None:
    session = MergeOptionsSession()
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

    chat_call = next(
        call for call in session.calls if call[0].endswith("/api/chat")
    )
    chat_payload = chat_call[1]
    assert chat_payload is not None
    assert chat_call[2] is True
    assert chat_payload["model"] == "gemma3"
    options_payload = chat_payload["options"]
    assert options_payload["num_predict"] == 32
    assert options_payload["temperature"] == pytest.approx(0.4)
    assert options_payload["top_p"] == pytest.approx(0.9)
    assert options_payload["stop"] == ["ALT"]
    assert options_payload["seed"] == 99


def test_ollama_provider_request_timeout_override() -> None:
    session = TimeoutOverrideSession()
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
