
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


def test_base_provider_name_returns_provider_id(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    provider = _DummyProvider(config)

    assert provider.name() == "mock-provider"


def test_base_provider_capabilities_default(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    provider = _DummyProvider(config)

    assert provider.capabilities() == {"chat"}
