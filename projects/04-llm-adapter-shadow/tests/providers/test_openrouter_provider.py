from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from llm_adapter.errors import (
    ProviderSkip,
    RateLimitError,
    RetriableError,
    SkipReason,
    TimeoutError,
)
from llm_adapter.provider_spi import ProviderRequest
from llm_adapter.providers.openrouter import OpenRouterProvider

from tests.helpers.fakes import FakeResponse, FakeSession


class _RecordingSession(FakeSession):
    def __init__(
        self,
        responder: Callable[[str, dict[str, Any] | None, bool, float | None], FakeResponse],
    ) -> None:
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


def test_openrouter_provider_builds_body_from_messages() -> None:
    payload = {
        "id": "chatcmpl-123",
        "model": "meta-llama/llama-3-8b-instruct:free",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url.endswith("/chat/completions")
        assert stream is False
        assert timeout == pytest.approx(10.0)
        assert body is not None
        assert body["model"] == "meta-llama/llama-3-8b-instruct:free"
        assert body["messages"] == [
            {"role": "system", "content": "stay calm"},
            {"role": "user", "content": "say hi"},
        ]
        assert body["max_tokens"] == 256
        assert body["temperature"] == pytest.approx(0.3)
        assert body["top_p"] == pytest.approx(0.9)
        assert body["stop"] == ["END"]
        return FakeResponse(status_code=200, payload=payload)

    session = _RecordingSession(responder)
    provider = OpenRouterProvider(
        "meta-llama/llama-3-8b-instruct:free",
        api_key="test-key",
        session=session,
        base_url="https://mock.openrouter.test/api/v1",
    )

    request = ProviderRequest(
        prompt="say hi",
        messages=[
            {"role": "system", "content": "stay calm"},
            {"role": "user", "content": "say hi"},
        ],
        timeout_s=10.0,
        temperature=0.3,
        top_p=0.9,
        stop=("END",),
        model="meta-llama/llama-3-8b-instruct:free",
    )

    response = provider.invoke(request)

    assert response.text == "Hello"
    assert response.token_usage.prompt == 11
    assert response.token_usage.completion == 7
    assert response.finish_reason == "stop"
    assert response.model == "meta-llama/llama-3-8b-instruct:free"
    assert response.latency_ms >= 0
    assert response.raw == payload


@pytest.mark.parametrize(
    "status_code, expected_exc",
    [
        (429, RateLimitError),
        (503, RetriableError),
    ],
)
def test_openrouter_provider_normalizes_http_errors(
    status_code: int, expected_exc: type[Exception]
) -> None:
    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        return FakeResponse(status_code=status_code, payload={"error": {"message": "boom"}})

    session = _RecordingSession(responder)
    provider = OpenRouterProvider(
        "meta-llama/llama-3-8b-instruct:free",
        api_key="test-key",
        session=session,
    )

    with pytest.raises(expected_exc):
        provider.invoke(ProviderRequest(prompt="hello", model="meta-llama/llama-3-8b-instruct:free"))


def test_openrouter_provider_skips_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = OpenRouterProvider(
        "meta-llama/llama-3-8b-instruct:free",
        api_key="",
    )

    with pytest.raises(ProviderSkip) as excinfo:
        provider.invoke(ProviderRequest(prompt="hello", model="meta-llama/llama-3-8b-instruct:free"))

    assert excinfo.value.reason is SkipReason.MISSING_OPENROUTER_API_KEY


def test_openrouter_provider_normalizes_timeout() -> None:
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

    provider = OpenRouterProvider(
        "meta-llama/llama-3-8b-instruct:free",
        api_key="test-key",
        session=Session(),
    )

    with pytest.raises(TimeoutError):
        provider.invoke(ProviderRequest(prompt="hello", model="meta-llama/llama-3-8b-instruct:free"))


def test_openrouter_provider_streams_and_collects_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://mock.openrouter.test/api")

    lines = [
        b"data: {\"choices\": [{\"delta\": {\"content\": \"Hel\"}}]}",
        b"data: {\"choices\": [{\"delta\": {\"content\": \"lo\"}}]}",
        b"data: {\"choices\": [{\"delta\": {}, \"finish_reason\": \"stop\", \"message\": {\"role\": \"assistant\", \"content\": \"Hello\"}}], \"usage\": {\"prompt_tokens\": 3, \"completion_tokens\": 5}}",
    ]

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url == "https://mock.openrouter.test/api/chat/completions"
        assert stream is True
        assert body is not None and body.get("stream") is True
        return FakeResponse(status_code=200, payload={}, lines=lines)

    session = _RecordingSession(responder)
    provider = OpenRouterProvider(
        "meta-llama/llama-3-8b-instruct:free",
        session=session,
        api_key=None,
        base_url=None,
    )

    request = ProviderRequest(
        prompt="hi",
        model="meta-llama/llama-3-8b-instruct:free",
        options={"stream": True},
    )

    response = provider.invoke(request)

    assert response.text == "Hello"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 5
    assert response.finish_reason == "stop"
    assert response.model == "meta-llama/llama-3-8b-instruct:free"
    assert response.latency_ms >= 0
    assert response.raw == {
        "choices": [
            {
                "delta": {},
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hello"},
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5},
    }
