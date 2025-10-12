from __future__ import annotations

import asyncio
from pathlib import Path

from adapter.cli import prompt_runner
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)


class _FailingProvider:
    def invoke(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


class _StrictProviderResponse:
    def __init__(
        self,
        *,
        text: str,
        latency_ms: int,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        token_usage: object | None = None,
    ) -> None:
        self.text = text
        self.latency_ms = latency_ms
        if token_usage is not None:
            tokens_in = getattr(token_usage, "prompt", tokens_in)
            tokens_out = getattr(token_usage, "completion", tokens_out)
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.input_tokens = tokens_in
        self.output_tokens = tokens_out


def test_execute_prompts_sets_error_kind_on_exception(monkeypatch):
    monkeypatch.setattr(prompt_runner, "ProviderResponse", _StrictProviderResponse)

    config = ProviderConfig(
        path=Path("provider.yml"),
        schema_version=None,
        provider="fake",
        endpoint=None,
        model="dummy",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=30,
        retries=RetryConfig(),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )

    def classify_error(exc, cfg, lang):  # type: ignore[no-untyped-def]
        return (f"friendly:{exc}", "provider")

    results = asyncio.run(
        prompt_runner.execute_prompts(
            ["hello"],
            _FailingProvider(),
            config,
            concurrency=1,
            rpm=0,
            lang="ja",
            classify_error=classify_error,
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.error == "friendly:boom"
    assert result.error_kind == "provider"
    assert result.response is None
