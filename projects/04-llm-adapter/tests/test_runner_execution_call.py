from __future__ import annotations

from pathlib import Path

from adapter.core.config import ProviderConfig, QualityGatesConfig, RateLimitConfig, RetryConfig, PricingConfig
from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.provider_spi import ProviderRequest
from adapter.core.runner_execution_call import ensure_invoke_compat


def _provider_config(tmp_path: Path) -> ProviderConfig:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider="mock-provider",
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


class _GenerateOnlyProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.captured: list[str] = []

    def generate(self, prompt: str) -> ProviderResponse:  # type: ignore[override]
        self.captured.append(prompt)
        return ProviderResponse(text=f"echo:{prompt}", latency_ms=0)


def test_ensure_invoke_compat_binds_generate(tmp_path: Path) -> None:
    provider = _GenerateOnlyProvider(_provider_config(tmp_path))
    ensure_invoke_compat(provider)

    request = ProviderRequest(model="dummy-model", prompt="hello", max_tokens=16, temperature=0.0, top_p=1.0)
    response = provider.invoke(request)

    assert provider.captured == ["hello"]
    assert response.text == "echo:hello"
