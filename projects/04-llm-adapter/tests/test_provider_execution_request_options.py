from __future__ import annotations

from pathlib import Path

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import BaseProvider, ProviderResponse


class _CapturingProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.last_request: ProviderRequest | None = None

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.last_request = request
        return ProviderResponse(text="ok", latency_ms=0)


def _build_provider_config(tmp_path: Path) -> ProviderConfig:
    return ProviderConfig(
        path=tmp_path / "config.yaml",
        schema_version=1,
        provider="stub",
        endpoint=None,
        model="test-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={
            "options": {"stream": True, "seed": 42},
            "metadata": {"tenant": "demo"},
        },
    )


def test_provider_request_receives_options_and_metadata(tmp_path: Path) -> None:
    provider_config = _build_provider_config(tmp_path)
    provider = _CapturingProvider(provider_config)
    executor = ProviderCallExecutor(backoff=None)

    executor.execute(provider_config, provider, "hello")

    assert provider.last_request is not None
    assert provider.last_request.options == {"stream": True, "seed": 42}
    assert provider.last_request.metadata == {"tenant": "demo"}
    assert provider.last_request.options is not provider_config.raw["options"]
