from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from src.llm_adapter.errors import RateLimitError, RetriableError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.openrouter import OpenRouterProvider


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        lines: Iterable[bytes] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self._lines = list(lines or [])

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload

    def iter_lines(self) -> Iterable[bytes]:
        yield from self._lines


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, "kwargs": kwargs})
        return self._responses.pop(0)


def test_openrouter_provider_sends_router_headers() -> None:
    response = FakeResponse(
        {
            "choices": [
                {"message": {"content": "hi"}, "text": "hi", "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
        headers={
            "x-router": "req-1",
            "x-router-model": "anthropic/claude-3",
            "x-router-provider": "anthropic",
        },
    )
    session = FakeSession([response])
    provider = OpenRouterProvider(
        "openrouter/auto",
        api_key="test-key",
        base_url="https://mock.openrouter.ai/api/v1",
        referer="https://example.com",
        title="Example",
        session=session,
    )

    request = ProviderRequest(
        prompt="hello",
        model="anthropic/claude-3,openai/gpt-4o",
        metadata={"router": {"provider": "anthropic"}},
    )
    result = provider.invoke(request)

    call = session.calls[0]
    assert call["url"] == "https://mock.openrouter.ai/api/v1/chat/completions"
    headers = call["kwargs"]["headers"]
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["HTTP-Referer"] == "https://example.com"
    assert headers["X-Title"] == "Example"
    assert headers["X-Router-Model"] == "anthropic/claude-3,openai/gpt-4o"
    assert headers["X-Router-Provider"] == "anthropic"
    payload = call["kwargs"]["json"]
    assert payload["model"] == "anthropic/claude-3"
    assert payload["messages"][0]["content"] == "hello"
    assert result.text == "hi"
    assert result.token_usage.prompt == 4
    assert result.token_usage.completion == 2
    assert result.raw["router"]["provider"] == "anthropic"


@pytest.mark.parametrize("status,expected", [(429, RateLimitError), (503, RetriableError)])
def test_openrouter_provider_normalizes_errors(
    status: int, expected: type[Exception]
) -> None:
    session = FakeSession([
        FakeResponse({"error": {"message": "bad"}}, status_code=status)
    ])
    provider = OpenRouterProvider("openrouter/auto", api_key="test-key", session=session)

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(prompt="hello", model="openrouter/auto"))


def test_openrouter_provider_aggregates_streaming() -> None:
    chunks = [
        b"data: {\"choices\":[{\"delta\":{\"content\":\"he\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\"llo\"},\"finish_reason\":\"stop\"}]}\n\n",
        b"data: [DONE]\n\n",
    ]
    session = FakeSession([FakeResponse({}, lines=chunks)])
    provider = OpenRouterProvider("openrouter/auto", api_key="test-key", session=session)

    request = ProviderRequest(prompt="hello", model="openrouter/auto", options={"stream": True})
    result = provider.invoke(request)

    call = session.calls[0]
    assert call["kwargs"]["stream"] is True
    assert result.text == "hello"
    assert result.finish_reason == "stop"
