from __future__ import annotations

from dataclasses import dataclass

import pytest

from adapter.core.compare_runner_support import _JudgeInvoker
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import BaseProvider
from adapter.core.provider_spi import ProviderRequest


@dataclass(slots=True)
class _StubProviderResponse:
    output_text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int


class _StubProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.last_prompt: str | None = None

    def invoke(self, request: ProviderRequest) -> _StubProviderResponse:  # type: ignore[override]
        self.last_prompt = request.prompt
        return _StubProviderResponse(
            output_text="judge-result",
            latency_ms=123,
            input_tokens=7,
            output_tokens=11,
        )


class _InvokeOnlyProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.last_request: ProviderRequest | None = None

    def invoke(self, request: ProviderRequest) -> _StubProviderResponse:  # type: ignore[override]
        self.last_request = request
        return _StubProviderResponse(
            output_text="judge-result",
            latency_ms=321,
            input_tokens=13,
            output_tokens=17,
        )

    def generate(self, prompt: str) -> _StubProviderResponse:  # type: ignore[override]
        raise AssertionError("generate must not be called")


@pytest.fixture()
def judge_provider_config(tmp_path_factory: pytest.TempPathFactory) -> ProviderConfig:
    path = tmp_path_factory.mktemp("cfg") / "provider.yaml"
    return ProviderConfig(
        path=path,
        schema_version=1,
        provider="stub",
        endpoint=None,
        model="stub-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=0,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def test_invoke_prefers_mapping_text(judge_provider_config: ProviderConfig) -> None:
    provider = _StubProvider(judge_provider_config)
    invoker = _JudgeInvoker(provider, judge_provider_config)

    response = invoker.invoke({"text": "expected-prompt"})

    assert provider.last_prompt == "expected-prompt"
    assert response.text == "judge-result"
    assert response.latency_ms == 123
    assert response.tokens_in == 7
    assert response.tokens_out == 11
    assert response.raw == {"provider": "stub"}


def test_invoke_uses_provider_request_path(judge_provider_config: ProviderConfig) -> None:
    provider = _InvokeOnlyProvider(judge_provider_config)
    invoker = _JudgeInvoker(provider, judge_provider_config)

    response = invoker.invoke({"prompt": "request-path"})

    assert provider.last_request is not None
    assert provider.last_request.prompt == "request-path"
    assert response.text == "judge-result"
    assert response.latency_ms == 321
    assert response.tokens_in == 13
    assert response.tokens_out == 17
    assert response.raw == {"provider": "stub"}
