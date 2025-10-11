
from __future__ import annotations

from pathlib import Path

from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.provider_spi import ProviderRequest, ProviderResponse
from adapter.core.providers import BaseProvider


def _provider_config(tmp_path: Path, provider: str) -> ProviderConfig:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider=provider,
        endpoint=None,
        model="dummy-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=30,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


class _DummyProvider(BaseProvider):
    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - not used
        raise NotImplementedError


def test_base_provider_generate_propagates_config_values(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    config.max_tokens = 128
    config.temperature = 0.42
    config.top_p = 0.73
    config.timeout_s = 45

    class _AssertingProvider(_DummyProvider):
        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            assert request.max_tokens == config.max_tokens
            assert request.temperature == config.temperature
            assert request.top_p == config.top_p
            assert request.timeout_s == float(config.timeout_s)
            return ProviderResponse(text="ok", latency_ms=0)

    provider = _AssertingProvider(config)

    provider.generate("hello world")


def test_base_provider_name_returns_provider_id(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    provider = _DummyProvider(config)

    assert provider.name() == "mock-provider"


def test_base_provider_capabilities_default(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    provider = _DummyProvider(config)

    assert provider.capabilities() == {"chat"}
