import asyncio
from pathlib import Path
import time

import pytest

from adapter.cli.prompt_runner import execute_prompts, RateLimiter
from adapter.core.config import ProviderConfig
from adapter.core.models import (
    PricingConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.provider_spi import ProviderRequest, ProviderResponse, TokenUsage


class _FakeClock:
    def __init__(self) -> None:
        self._now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self._now += delay


@pytest.mark.asyncio
async def test_rate_limiter_wait_respects_zero_and_one(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    limiter_zero = RateLimiter(0, monotonic=clock.monotonic)
    await limiter_zero.wait()
    assert clock.sleeps == []

    limiter_one = RateLimiter(1, monotonic=clock.monotonic)
    monkeypatch.setattr(asyncio, "sleep", clock.sleep)

    await limiter_one.wait()
    assert clock.sleeps == []

    await limiter_one.wait()
    assert clock.sleeps == [pytest.approx(60.0)]

    await limiter_one.wait()
    assert clock.sleeps[-1] == pytest.approx(60.0)


class _DummyProvider:
    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if request.prompt == "fail":
            raise RuntimeError("boom")
        if request.prompt == "slow":
            time.sleep(0.01)
        return ProviderResponse(
            text=request.prompt,
            latency_ms=0,
            token_usage=TokenUsage(prompt=1, completion=1),
        )


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        path=Path("/tmp/config.json"),
        schema_version=1,
        provider="dummy",
        endpoint=None,
        model="dummy-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


@pytest.mark.asyncio
async def test_execute_prompts_sorts_results_and_propagates_error_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _DummyProvider()
    config = _provider_config()

    def classify_error(exc: Exception, _: ProviderConfig, lang: str) -> tuple[str, str]:
        return (f"{lang}:{exc}", "temporary")

    original_gather = asyncio.gather

    async def gather_and_reverse(*args: object, **kwargs: object) -> tuple[object, ...]:
        results = await original_gather(*args, **kwargs)
        reversed_results = tuple(reversed(results))
        return reversed_results

    monkeypatch.setattr(asyncio, "gather", gather_and_reverse)

    results = await execute_prompts(
        ["slow", "fast", "fail"],
        provider,
        config,
        concurrency=2,
        rpm=0,
        lang="ja",
        classify_error=classify_error,
    )

    assert [result.index for result in results] == [0, 1, 2]
    assert results[-1].error_kind == "temporary"
    assert results[-1].error == "ja:boom"
