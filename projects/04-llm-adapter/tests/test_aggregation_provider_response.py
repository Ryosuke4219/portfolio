from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapter.core.aggregation_selector_components import CandidateBuilder
from adapter.core.compare_runner_support import _JudgeInvoker
from adapter.core.metrics import RunMetrics
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.runner_execution import SingleRunResult


_BASE_METRICS = dict(
    ts="2024-01-01T00:00:00Z",
    run_id="run",
    mode="consensus",
    prompt_id="prompt",
    prompt_name="Prompt",
    seed=0,
    temperature=0.0,
    top_p=1.0,
    max_tokens=16,
    input_tokens=1,
    output_tokens=1,
    latency_ms=1,
    cost_usd=0.0,
    status="ok",
    failure_kind=None,
    error_message=None,
    output_text=None,
    output_hash=None,
)


def _metrics(provider: str) -> RunMetrics:
    payload = dict(_BASE_METRICS)
    payload.update(provider=provider, model=f"{provider}-model")
    return RunMetrics(**payload)


def test_candidate_builder_uses_provider_response() -> None:
    builder = CandidateBuilder()
    batch = [(0, SingleRunResult(metrics=_metrics("p1"), raw_output="Alpha"))]

    [candidate] = builder.build(batch)

    assert isinstance(candidate.response, ProviderResponse)
    assert candidate.response.text == "Alpha"
    assert candidate.response.token_usage.prompt == 1
    assert candidate.response.token_usage.completion == 1


@dataclass(slots=True)
class _StubProviderResponse:
    text: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    raw: Any | None = None


class _StubProvider(BaseProvider):
    def __init__(self, config: ProviderConfig, response: _StubProviderResponse) -> None:
        super().__init__(config)
        self._response = response

    def generate(self, prompt: str) -> _StubProviderResponse:  # type: ignore[override]
        return self._response


def _provider_config(path: Path) -> ProviderConfig:
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


def test_judge_invoker_returns_provider_response(tmp_path) -> None:
    config = _provider_config(tmp_path / "provider.yaml")
    provider = _StubProvider(
        config,
        _StubProviderResponse(text="0.75", latency_ms=42, tokens_in=3, tokens_out=5),
    )
    invoker = _JudgeInvoker(provider, config)

    response = invoker.invoke({"text": "ignored"})

    assert isinstance(response, ProviderResponse)
    assert response.text == "0.75"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 5
    assert response.raw == {"provider": "stub"}
