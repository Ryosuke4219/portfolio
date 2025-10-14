from __future__ import annotations

import pytest
from llm_adapter.errors import AuthError, RateLimitError, TimeoutError
from llm_adapter.provider_spi import ProviderRequest
from llm_adapter.providers.ollama import OllamaProvider

from tests.helpers.fakes import FakeResponse

from .conftest import BaseChatSession


class AutoPullErrorSession(BaseChatSession):
    def __init__(self, status_code: int) -> None:
        super().__init__()
        self._status_code = status_code
        self.pull_response: FakeResponse | None = None

    def handle_show(self) -> FakeResponse:
        self._show_calls += 1
        if self._show_calls == 1:
            return FakeResponse(status_code=404, payload={})
        return FakeResponse(status_code=200, payload={})

    def handle_pull(self, *, stream: bool) -> FakeResponse:
        assert stream is True
        response = FakeResponse(status_code=self._status_code, payload={})
        self.pull_response = response
        return response

    def handle_chat(
        self,
        *,
        json: dict[str, object] | None,
        timeout: float | None,
        stream: bool,
    ) -> FakeResponse:
        raise AssertionError("chat should not be called when pull fails")


class ChatErrorSession(BaseChatSession):
    def __init__(self, status_code: int) -> None:
        super().__init__()
        self._status_code = status_code
        self.last_chat_response: FakeResponse | None = None

    def handle_chat(
        self,
        *,
        json: dict[str, object] | None,
        timeout: float | None,
        stream: bool,
    ) -> FakeResponse:
        response = FakeResponse(status_code=self._status_code, payload={})
        self.last_chat_response = response
        return response


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
    session = AutoPullErrorSession(status_code)
    provider = OllamaProvider(provider_request_model, session=session, host="http://localhost")

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))

    assert session.pull_response is not None
    assert session.pull_response.closed


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
    session = ChatErrorSession(status_code)
    provider = OllamaProvider("gemma3n:e2b", session=session, host="http://localhost")

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(prompt="hello", model="gemma3n:e2b"))

    assert session.last_chat_response is not None
    assert session.last_chat_response.closed
