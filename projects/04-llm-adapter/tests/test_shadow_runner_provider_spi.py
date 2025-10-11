from __future__ import annotations

from pathlib import Path

from adapter.core.config import ProviderConfig
from adapter.core.execution import shadow_runner as shadow_module
from adapter.core.execution.shadow_runner import ShadowRunner
from adapter.core.models import (
    PricingConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI


class _StubProvider(ProviderSPI):
    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    def name(self) -> str:
        return "stub"

    def capabilities(self) -> set[str]:  # pragma: no cover - not used in test
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(text="ok", latency_ms=42)


def _provider_config(tmp_path: Path) -> ProviderConfig:
    config_path = tmp_path / "provider.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider="stub",
        endpoint=None,
        model="stub-model",
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


def test_shadow_runner_uses_canonical_provider_spi(tmp_path: Path) -> None:
    provider = _StubProvider()
    config = _provider_config(tmp_path)

    runner = ShadowRunner(provider)
    runner.start(provider_config=config, prompt="hello")
    result = runner.finalize()

    assert shadow_module.ProviderSPI is ProviderSPI
    assert result is not None
    assert result.status == "ok"
    assert result.provider_id == provider.name()
    assert provider.requests and provider.requests[0].model == config.model

