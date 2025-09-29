from __future__ import annotations

import pytest

from src.llm_adapter.provider_spi import (
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
)


def test_provider_request_builds_messages_from_prompt(
    provider_request_model: str,
) -> None:
    request = ProviderRequest(prompt="  hello ", model=provider_request_model)
    assert request.prompt_text == "hello"
    assert request.chat_messages == [{"role": "user", "content": "hello"}]
    assert request.stop is None


def test_provider_request_normalizes_messages_and_stop(
    provider_request_model: str,
) -> None:
    request = ProviderRequest(
        prompt="",
        messages=[{"role": "User", "content": [" hi ", " there "]}],
        stop=tuple([" END ", ""]),
        model=provider_request_model,
    )
    assert request.prompt_text == "hi"
    assert request.chat_messages == [{"role": "User", "content": ["hi", "there"]}]
    assert request.stop == ("END",)


def test_provider_request_timeout_defaults_to_30_seconds(
    provider_request_model: str,
) -> None:
    request = ProviderRequest(model=provider_request_model)
    assert request.timeout_s == pytest.approx(30.0)


def test_provider_request_rejects_empty_model() -> None:
    with pytest.raises(ValueError):
        ProviderRequest(model="", prompt="hello")
    with pytest.raises(ValueError):
        ProviderRequest(model="   ", prompt="hello")


def test_provider_request_requires_model_argument() -> None:
    with pytest.raises(ValueError):
        ProviderRequest(prompt="hello")


def test_provider_response_populates_token_usage_from_inputs() -> None:
    response = ProviderResponse(text="ok", latency_ms=10, tokens_in=3, tokens_out=4)
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 4
    assert response.input_tokens == 3
    assert response.output_tokens == 4


def test_provider_response_uses_token_usage_if_provided() -> None:
    usage = TokenUsage(prompt=5, completion=7)
    response = ProviderResponse(text="ok", latency_ms=10, token_usage=usage)
    assert response.tokens_in == 5
    assert response.tokens_out == 7
    assert response.token_usage is usage
