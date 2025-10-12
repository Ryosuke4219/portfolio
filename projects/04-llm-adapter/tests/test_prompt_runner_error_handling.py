import pytest

from adapter.cli.prompt_runner import execute_prompts
from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)


class _RaisingProvider:
    def invoke(self, request):  # pragma: no cover - メソッド署名互換のみ
        raise RuntimeError("boom")


def _classify_error(exc: Exception, config: ProviderConfig, lang: str) -> tuple[str, str]:
    return ("handled", "provider_error")


@pytest.mark.asyncio
async def test_execute_prompts_sets_error_kind_when_provider_raises(tmp_path) -> None:
    config = ProviderConfig(
        path=tmp_path / "provider.yaml",
        schema_version=1,
        provider="dummy",
        endpoint="responses",
        model="dummy-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=128,
        timeout_s=30,
        retries=RetryConfig(),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )

    provider = _RaisingProvider()

    results = await execute_prompts(
        prompts=["hello"],
        provider=provider,
        config=config,
        concurrency=1,
        rpm=0,
        lang="ja",
        classify_error=_classify_error,
    )

    assert len(results) == 1
    result = results[0]
    assert result.error == "handled"
    assert result.error_kind == "provider_error"
    assert result.response is None
