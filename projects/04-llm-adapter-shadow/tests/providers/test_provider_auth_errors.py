from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from src.llm_adapter.errors import AuthError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.base import BaseProvider
from src.llm_adapter.providers.openai import OpenAIProvider
from src.llm_adapter.providers.openrouter import OpenRouterProvider
from tests.helpers.fakes import FakeResponse, FakeSession


class _UnauthorizedSession(FakeSession):
    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.calls.append((url, json, stream))
        return FakeResponse(
            status_code=401,
            payload={"error": {"message": "invalid credentials"}},
        )


@pytest.mark.parametrize(
    "provider_factory",
    [
        lambda session: OpenAIProvider("gpt-4o-mini", api_key="bad", session=session),
        lambda session: OpenRouterProvider("gpt-4o-mini", api_key="bad", session=session),
    ],
)
def test_providers_raise_auth_error_on_unauthorized_response(
    provider_factory: Callable[[FakeSession], BaseProvider],
) -> None:
    session = _UnauthorizedSession()
    provider = provider_factory(session)

    with pytest.raises(AuthError):
        provider.invoke(ProviderRequest(prompt="hello", model="gpt-4o-mini"))

    assert session.calls, "expected POST request to be recorded"
