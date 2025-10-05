from __future__ import annotations

from pathlib import Path

from adapter.core.datasets import GoldenTask
from adapter.core.errors import RateLimitError
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.provider_spi import TokenUsage
from adapter.core.providers import BaseProvider, ProviderResponse


class RateLimitStubProvider(BaseProvider):
    def __init__(self, config: ProviderConfig, *, failures: int) -> None:
        super().__init__(config)
        self._failures = failures
        self.calls = 0

    def generate(self, prompt: str) -> ProviderResponse:
        self.calls += 1
        if self.calls <= self._failures:
            raise RateLimitError("rate limited")
        return ProviderResponse(
            text="recovered",
            latency_ms=5,
            token_usage=TokenUsage(prompt=1, completion=1),
        )


class SuccessProvider(BaseProvider):
    def generate(self, prompt: str) -> ProviderResponse:
        return ProviderResponse(
            text="success",
            latency_ms=3,
            token_usage=TokenUsage(prompt=1, completion=1),
        )


class TrackingProvider(BaseProvider):
    def __init__(self, config: ProviderConfig, response: ProviderResponse) -> None:
        super().__init__(config)
        self._response = response
        self.calls = 0

    def generate(self, prompt: str) -> ProviderResponse:
        self.calls += 1
        return self._response


class UnusedProvider(BaseProvider):
    def generate(self, prompt: str) -> ProviderResponse:  # pragma: no cover - defensive
        raise AssertionError("unused provider should not be invoked")


def make_provider_config(
    tmp_path: Path, name: str, *, retries: RetryConfig | None = None
) -> ProviderConfig:
    retry_config = retries or RetryConfig()
    return ProviderConfig(
        path=tmp_path / f"{name}.yaml",
        schema_version=1,
        provider=name,
        endpoint=None,
        model=f"model-{name}",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=10,
        timeout_s=0,
        retries=retry_config,
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def make_task() -> GoldenTask:
    return GoldenTask(
        task_id="task",
        name="Task",
        input={},
        prompt_template="prompt",
        expected={},
    )


__all__ = [
    "RateLimitStubProvider",
    "SuccessProvider",
    "TrackingProvider",
    "UnusedProvider",
    "make_provider_config",
    "make_task",
]
