from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

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
from adapter.core.aggregation_selector_components import SchemaCache


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
    output_hash=None,
)


def _metrics(provider: str, *, latency_ms: int = 1, cost_usd: float = 0.0) -> RunMetrics:
    payload = dict(_BASE_METRICS)
    payload.update(
        provider=provider,
        model=f"{provider}-model",
        output_text=provider,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
    return RunMetrics(**payload)


def _judge_config() -> ProviderConfig:
    return ProviderConfig(
        path=Path("judge.yaml"),
        schema_version=1,
        provider="judge",
        endpoint=None,
        model="judge-model",
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
        raw={},
    )


class _StubJudge:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.requests: list[dict[str, object]] = []

    def invoke(self, request: dict[str, object]) -> SimpleNamespace:
        self.requests.append(request)
        score = self._scores[len(self.requests) - 1]
        return SimpleNamespace(text=str(score), raw={"quality_score": score})


class _StubFactory:
    def __init__(self, judge: _StubJudge) -> None:
        self._judge = judge
        self.create_calls: list[str] = []

    def create(self, *, model: str) -> _StubJudge:
        self.create_calls.append(model)
        return self._judge


def test_max_score_propagates_judge_scores() -> None:
    judge_config = _judge_config()
    judge = _StubJudge([0.4, 0.9])
    factory = _StubFactory(judge)

    def builder(config: ProviderConfig) -> _StubFactory:
        assert config is judge_config
        return factory

    selector = AggregationSelector(judge_factory_builder=builder)
    config = RunnerConfig(mode="consensus", aggregate="max")
    batch = [
        (0, SingleRunResult(metrics=_metrics("p1"), raw_output="Alpha")),
        (1, SingleRunResult(metrics=_metrics("p2"), raw_output="Beta")),
    ]

    decision = selector.select("consensus", config, batch, default_judge_config=judge_config)

    assert decision is not None
    scores = {candidate.provider: candidate.score for candidate in decision.decision.candidates}
    assert scores == {"p1": 0.4, "p2": 0.9}
    assert decision.decision.metadata == {"scores": {"p1": 0.4, "p2": 0.9}}


def test_tie_breaker_falls_back_to_latency_cost_stable_order() -> None:
    selector = AggregationSelector(judge_factory_builder=lambda config: _StubFactory(_StubJudge([])))
    config = RunnerConfig(mode="consensus", aggregate="majority")
    batch = [
        (
            0,
            SingleRunResult(metrics=_metrics("p1", latency_ms=20, cost_usd=1.0), raw_output="Same"),
        ),
        (
            1,
            SingleRunResult(metrics=_metrics("p2", latency_ms=10, cost_usd=5.0), raw_output="Same"),
        ),
    ]

    decision = selector.select("consensus", config, batch, default_judge_config=None)

    assert decision is not None
    assert decision.decision.tie_breaker_used == "latency"
    assert decision.decision.chosen.provider == "p2"


def test_schema_cache_reads_schema_only_once(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    selector = AggregationSelector(judge_factory_builder=lambda config: _StubFactory(_StubJudge([])))
    config = RunnerConfig(mode="consensus", aggregate="majority", schema=schema_path)
    batch = [
        (0, SingleRunResult(metrics=_metrics("p1"), raw_output="One")),
        (1, SingleRunResult(metrics=_metrics("p2"), raw_output="Two")),
    ]
    calls: list[None] = []

    def fake_json_load(fp: object) -> dict[str, object]:
        calls.append(None)
        return {}

    monkeypatch.setattr(
        "adapter.core.aggregation_selector_components.json.load",
        fake_json_load,
    )

    decision1 = selector.select("consensus", config, batch, default_judge_config=None)
    decision2 = selector.select("consensus", config, batch, default_judge_config=None)

    assert decision1 is not None
    assert decision2 is not None
    assert calls == [None]


def test_schema_cache_resets_when_path_removed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    cache = SchemaCache()
    calls: list[str] = []

    def fake_json_load(fp: object) -> dict[str, object]:
        calls.append("initial")
        return {}

    monkeypatch.setattr(
        "adapter.core.aggregation_selector_components.json.load",
        fake_json_load,
    )

    assert cache.load(schema_path) == {}
    assert cache.load(None) is None

    schema_path.write_text("{\n  \"key\": 1\n}", encoding="utf-8")

    def fake_json_load_updated(fp: object) -> dict[str, object]:
        calls.append("updated")
        return {"key": 1}

    monkeypatch.setattr(
        "adapter.core.aggregation_selector_components.json.load",
        fake_json_load_updated,
    )

    assert cache.load(schema_path) == {"key": 1}
    assert calls == ["initial", "updated"]


def test_tie_breaker_falls_back_to_cost_when_latency_equal() -> None:
    selector = AggregationSelector(judge_factory_builder=lambda config: _StubFactory(_StubJudge([])))
    config = RunnerConfig(mode="consensus", aggregate="majority")
    batch = [
        (
            0,
            SingleRunResult(metrics=_metrics("p1", latency_ms=10, cost_usd=5.0), raw_output="Same"),
        ),
        (
            1,
            SingleRunResult(metrics=_metrics("p2", latency_ms=10, cost_usd=1.0), raw_output="Same"),
        ),
    ]

    decision = selector.select("consensus", config, batch, default_judge_config=None)

    assert decision is not None
    assert decision.decision.tie_breaker_used == "cost"
    assert decision.decision.chosen.provider == "p2"
