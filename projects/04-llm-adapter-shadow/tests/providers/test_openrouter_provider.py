from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from src.llm_adapter.errors import RateLimitError, RetriableError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.openrouter import OpenRouterProvider
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


def test_openrouter_provider_maps_rate_limit_error() -> None:
    error_payload = {
        "error": {
            "type": "rate_limit",
            "code": "rate_limit_exceeded",
            "message": "too many requests",
            "docs": "https://openrouter.ai/docs#rate-limits",
        }
    }

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert url.endswith("/chat/completions")
        assert stream is False
        assert body is not None
        assert body["model"] == "openrouter/test-model"
        return FakeResponse(status_code=429, payload=error_payload)

    session = _RecordingSession(responder)
    provider = OpenRouterProvider(
        "openrouter/test-model",
        api_key="test-key",
        session=session,
    )

    request = ProviderRequest(prompt="hello", model="openrouter/test-model")

    with pytest.raises(RateLimitError) as exc_info:
        provider.invoke(request)

    assert "too many requests" in str(exc_info.value)


def test_openrouter_provider_maps_retriable_error() -> None:
    error_payload = {
        "error": {
            "type": "server_error",
            "code": "upstream_overloaded",
            "message": "try again later",
        }
    }

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is False
        return FakeResponse(status_code=503, payload=error_payload)

    session = _RecordingSession(responder)
    provider = OpenRouterProvider(
        "openrouter/test-model",
        api_key="test-key",
        session=session,
    )

    request = ProviderRequest(prompt="status?", model="openrouter/test-model")

    with pytest.raises(RetriableError) as exc_info:
        provider.invoke(request)

    assert "try again later" in str(exc_info.value)


def test_openrouter_provider_streams_and_collects_chunks() -> None:
    final_event = {
        "type": "message.completed",
        "message": {
            "role": "assistant",
            "content": "Hello",
        },
        "usage": {
            "input_tokens": 9,
            "output_tokens": 4,
        },
        "model": "openrouter/test-model",
        "finish_reason": "stop",
    }

    lines = [
        b"data: {\"type\": \"message.delta\", \"delta\": {\"content\": \"Hel\"}}\n\n",
        b"data: {\"type\": \"message.delta\", \"delta\": {\"content\": \"lo\"}}\n\n",
        b"data: {\"type\": \"message.completed\", \"message\": {\"role\": \"assistant\", \"content\": \"Hello\"}, \"usage\": {\"input_tokens\": 9, \"output_tokens\": 4}, \"model\": \"openrouter/test-model\", \"finish_reason\": \"stop\"}\n\n",
        b"data: [DONE]\n\n",
    ]

    def responder(
        url: str,
        body: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is True
        assert body is not None
        assert body.get("stream") is True
        assert body.get("model") == "openrouter/test-model"
        return FakeResponse(status_code=200, payload={}, lines=lines)

    session = _RecordingSession(responder)
    provider = OpenRouterProvider(
        "openrouter/test-model",
        api_key="env-key",
        session=session,
    )

    request = ProviderRequest(
        prompt="hello",
        model="openrouter/test-model",
        options={"stream": True},
    )

    response = provider.invoke(request)

    assert response.text == "Hello"
    assert response.token_usage.prompt == 9
    assert response.token_usage.completion == 4
    assert response.finish_reason == "stop"
    assert response.model == "openrouter/test-model"
    assert response.raw == final_event
