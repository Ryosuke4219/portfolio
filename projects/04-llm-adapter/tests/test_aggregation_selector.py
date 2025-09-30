from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from adapter.core.aggregation_selector import AggregationSelector
from adapter.core.metrics import RunMetrics
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult

_BASE_METRICS = dict(
    ts="2024-01-01T00:00:00Z", run_id="run", mode="consensus",
    prompt_id="prompt", prompt_name="Prompt", seed=0,
    temperature=0.0, top_p=1.0, max_tokens=16,
    input_tokens=1, output_tokens=1, latency_ms=1,
    cost_usd=0.0, status="ok", failure_kind=None,
    error_message=None, output_hash=None,
)


def _metrics(provider: str, text: str) -> RunMetrics:
    return RunMetrics(provider=provider, model=f"{provider}-model", output_text=text, **_BASE_METRICS)


def _judge_config() -> ProviderConfig:
    return ProviderConfig(
        path=Path("judge.yaml"), schema_version=1, provider="judge",
        endpoint=None, model="judge-model", auth_env=None,
        seed=0, temperature=0.0, top_p=1.0, max_tokens=16,
        timeout_s=0, retries=RetryConfig(), persist_output=True,
        pricing=PricingConfig(), rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(), raw={},
    )


class _DummyJudge:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke(self, request: dict[str, object]) -> SimpleNamespace:
        self.calls.append(request)
        provider = request["provider"]
        score = 0.1 if provider == "p1" else 0.9
        return SimpleNamespace(text=str(score), raw={"quality_score": score})


class _DummyFactory:
    def __init__(self, judge: _DummyJudge) -> None:
        self._judge = judge
        self.create_calls: list[str] = []

    def create(self, *, model: str) -> _DummyJudge:
        self.create_calls.append(model)
        return self._judge


def test_max_score_selects_highest_quality() -> None:
    judge_config = _judge_config()
    judge = _DummyJudge()
    factory = _DummyFactory(judge)
    builder_calls: list[ProviderConfig] = []

    def builder(config: ProviderConfig) -> _DummyFactory:
        builder_calls.append(config); return factory

    selector = AggregationSelector(judge_factory_builder=builder)
    config = RunnerConfig(mode="consensus", aggregate="max")
    batch = [
        (0, SingleRunResult(metrics=_metrics("p1", "Alpha"), raw_output="Alpha")),
        (1, SingleRunResult(metrics=_metrics("p2", "Beta"), raw_output="Beta")),
    ]
    decision = selector.select("consensus", config, batch, default_judge_config=judge_config)

    assert decision is not None
    assert builder_calls == [judge_config]
    assert factory.create_calls == ["judge-model"]
    assert [call["provider"] for call in judge.calls] == ["p1", "p2"]
    scores = {candidate.provider: candidate.score for candidate in decision.decision.candidates}
    assert scores == {"p1": 0.1, "p2": 0.9}
    assert decision.decision.metadata == {"scores": {"p1": 0.1, "p2": 0.9}}
    assert decision.decision.chosen.provider == "p2"
