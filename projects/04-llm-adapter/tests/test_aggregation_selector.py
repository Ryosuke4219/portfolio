import pytest

from adapter.core.aggregation import AggregationResult
from adapter.core.aggregation_controller import AggregationController
from adapter.core.aggregation_selector import AggregationSelector
from adapter.core.metrics import RunMetrics
from adapter.core.runner_api import BackoffPolicy, RunnerConfig
from adapter.core.runner_execution import SingleRunResult


def _make_result(provider: str, output: str) -> SingleRunResult:
    metrics = RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id="run",
        provider=provider,
        model="model",
        mode="consensus",
        prompt_id="prompt",
        prompt_name="Prompt",
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        input_tokens=1,
        output_tokens=1,
        latency_ms=100,
        cost_usd=0.1,
        status="ok",
        failure_kind=None,
        error_message=None,
        output_text=output,
        output_hash=None,
    )
    return SingleRunResult(metrics=metrics, raw_output=output)


def _make_config(*, aggregate: str, provider_weights: dict[str, float] | None) -> RunnerConfig:
    return RunnerConfig(
        mode="consensus",
        aggregate=aggregate,
        quorum=1,
        tie_breaker=None,
        provider_weights=provider_weights,
        schema=None,
        judge=None,
        judge_provider=None,
        max_concurrency=None,
        rpm=None,
        backoff=BackoffPolicy(),
        shadow_provider=None,
        metrics_path=None,
    )


def test_weighted_vote_requires_weights() -> None:
    selector = AggregationSelector()
    config = _make_config(aggregate="weighted_vote", provider_weights=None)
    with pytest.raises(ValueError, match="provider_weights"):
        selector._resolve_aggregation_strategy(
            "consensus",
            config,
            default_judge_config=None,
        )


def test_weighted_vote_merges_metadata_and_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = AggregationSelector()
    config = _make_config(
        aggregate="weighted_vote",
        provider_weights={"p1": 1.0, "p2": 0.5},
    )
    captured: dict[str, object] = {}

    class DummyStrategy:
        name = "weighted_vote"

        def aggregate(self, candidates, *, tiebreaker=None):  # type: ignore[override]
            return AggregationResult(
                chosen=candidates[0],
                candidates=list(candidates),
                strategy="weighted_vote",
                reason="dummy",
                tie_breaker_used=None,
                metadata={"bucket_size": len(candidates)},
            )

    def fake_from_string(kind: str, **kwargs: object) -> DummyStrategy:
        captured["kind"] = kind
        captured["kwargs"] = kwargs
        return DummyStrategy()

    monkeypatch.setattr(
        "adapter.core.aggregation.AggregationStrategy.from_string",
        staticmethod(fake_from_string),
    )

    batch = [(0, _make_result("p1", "A")), (1, _make_result("p2", "B"))]

    decision = selector.select(
        "consensus",
        config,
        batch,
        default_judge_config=None,
    )
    assert decision is not None
    assert captured["kind"] == "weighted_vote"
    assert captured["kwargs"]["weights"] == {"p1": 1.0, "p2": 0.5}
    assert decision.decision.metadata is not None
    assert decision.decision.metadata["provider_weights"] == {"p1": 1.0, "p2": 0.5}

    controller = AggregationController()
    apply_batch = [(0, _make_result("p1", "A")), (1, _make_result("p2", "B"))]
    controller.apply(
        mode="consensus",
        config=config,
        batch=apply_batch,
        default_judge_config=None,
    )
    winner = apply_batch[0][1]
    meta = winner.metrics.ci_meta
    assert meta["aggregate_provider_weights"] == {"p1": 1.0, "p2": 0.5}
    consensus_meta = meta["consensus"]
    assert consensus_meta["metadata"]["provider_weights"] == {"p1": 1.0, "p2": 0.5}
