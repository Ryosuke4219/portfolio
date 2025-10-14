from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from llm_adapter.errors import RateLimitError, RetriableError, TimeoutError
from llm_adapter.provider_spi import ProviderRequest
from llm_adapter.providers.openai import OpenAIProvider

from tests.helpers.fakes import FakeResponse, FakeSession


class _RecordingSession(FakeSession):
    def __init__(
        self,
        responder: Callable[[str, dict[str, Any] | None, bool, float | None], FakeResponse],
    ):
        super().__init__()
        self._responder = responder
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
        self.last_timeout = timeout
        self.last_payload = json
        return self._responder(url, json, stream, timeout)


def test_openai_provider_builds_body_from_prompt_and_messages() -> None:
    payload = {
        "id": "resp_123",
        "model": "gpt-4o-mini",
        "output": [
            {
                "content": [
                    {"type": "output_text", "text": "Hello"},
                ]
            }
        ],
        "usage": {"input_tokens": 11, "output_tokens": 7},
        "finish_reason": "stop",
    }

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url.endswith("/responses")
        assert stream is False
        assert timeout == pytest.approx(12.5)
        assert body is not None
        assert body["model"] == "gpt-4o-mini"
        assert body["input"] == "user says hi"
        assert body["messages"] == [
            {"role": "system", "content": "stay calm"},
            {"role": "user", "content": "user says hi"},
        ]
        assert body["max_output_tokens"] == 256
        assert body["temperature"] == pytest.approx(0.4)
        assert body["top_p"] == pytest.approx(0.8)
        assert body["stop"] == ["END"]
        return FakeResponse(status_code=200, payload=payload)

    session = _RecordingSession(responder)
    provider = OpenAIProvider(
        "gpt-4o-mini",
        api_key="test-key",
        session=session,
    )

    request = ProviderRequest(
        prompt="user says hi",
        messages=[
            {"role": "system", "content": "stay calm"},
            {"role": "user", "content": "user says hi"},
        ],
        timeout_s=12.5,
        temperature=0.4,
        top_p=0.8,
        stop=("END",),
        model="gpt-4o-mini",
    )

    response = provider.invoke(request)

    assert response.text == "Hello"
    assert response.token_usage.prompt == 11
    assert response.token_usage.completion == 7
    assert response.finish_reason == "stop"
    assert response.model == "gpt-4o-mini"
    assert response.latency_ms >= 0
    assert response.raw == payload


@pytest.mark.parametrize(
    "status_code, expected_exc",
    [
        (429, RateLimitError),
        (500, RetriableError),
    ],
)
def test_openai_provider_normalizes_http_errors(
    status_code: int, expected_exc: type[Exception]
) -> None:
    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        return FakeResponse(
            status_code=status_code,
            payload={"error": {"message": "boom"}},
        )

    session = _RecordingSession(responder)
    provider = OpenAIProvider(
        "gpt-4o-mini",
        api_key="test-key",
        session=session,
    )

    with pytest.raises(expected_exc):
        provider.invoke(ProviderRequest(prompt="hello", model="gpt-4o-mini"))


def test_openai_provider_normalizes_timeout() -> None:
    class Session(FakeSession):
        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            from llm_adapter.providers._requests_compat import requests_exceptions

            raise requests_exceptions.Timeout("timeout")

    provider = OpenAIProvider(
        "gpt-4o-mini",
        api_key="test-key",
        session=Session(),
    )

    with pytest.raises(TimeoutError):
        provider.invoke(ProviderRequest(prompt="hello", model="gpt-4o-mini"))


def test_openai_provider_streams_and_collects_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    final_chunk = {
        "type": "response.completed",
        "response": {
            "model": "gpt-4o-mini",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "Hello"},
                    ]
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 5},
        },
        "finish_reason": "stop",
    }

    lines = [
        b"{\"type\": \"response.output_text.delta\", \"delta\": \"Hel\"}",
        b"{\"type\": \"response.output_text.delta\", \"delta\": \"lo\"}",
        b"{\"type\": \"response.completed\", \"response\": {\"model\": \"gpt-4o-mini\", \"output\": [{\"content\": [{\"type\": \"output_text\", \"text\": \"Hello\"}]}], \"usage\": {\"input_tokens\": 3, \"output_tokens\": 5}}, \"finish_reason\": \"stop\"}",
    ]

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is True
        return FakeResponse(status_code=200, payload={}, lines=lines)

    session = _RecordingSession(responder)
    provider = OpenAIProvider(
        "gpt-4o-mini",
        session=session,
        api_key=None,
    )

    request = ProviderRequest(
        prompt="hi",
        model="gpt-4o-mini",
        options={"stream": True},
    )

    response = provider.invoke(request)

    assert response.text == "Hello"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 5
    assert response.finish_reason == "stop"
    assert response.model == "gpt-4o-mini"
    assert response.latency_ms >= 0
    assert response.raw == final_chunk["response"]
