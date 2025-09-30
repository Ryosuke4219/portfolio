from __future__ import annotations

from adapter.core.aggregation import AggregationCandidate, MajorityVoteStrategy
from adapter.core.aggregation_controller import AggregationController
from adapter.core.metrics import RunMetrics
from adapter.core.providers import ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult


def _make_candidate(index: int, text: str, *, latency: int = 100) -> AggregationCandidate:
    response = ProviderResponse(output_text=text, latency_ms=latency)
    return AggregationCandidate(
        index=index,
        provider=f"provider-{index}",
        response=response,
        text=text,
    )


def _make_metrics(
    *,
    provider: str,
    model: str,
    latency: int,
    cost: float,
    status: str = "ok",
    output: str = "",
) -> RunMetrics:
    return RunMetrics(
        ts="0",
        run_id="run",
        provider=provider,
        model=model,
        mode="consensus",
        prompt_id="prompt-id",
        prompt_name="prompt",
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=1,
        input_tokens=1,
        output_tokens=1,
        latency_ms=latency,
        cost_usd=cost,
        status=status,
        failure_kind=None,
        error_message=None,
        output_text=output,
        output_hash=None,
    )


def _make_result(index: int, text: str, *, latency: int, cost: float) -> tuple[int, SingleRunResult]:
    metrics = _make_metrics(
        provider=f"provider-{index}",
        model=f"model-{index}",
        latency=latency,
        cost=cost,
        output=text,
    )
    return index, SingleRunResult(metrics=metrics, raw_output=text)


def test_majority_vote_normalizes_strings() -> None:
    strategy = MajorityVoteStrategy()
    candidates = [
        _make_candidate(0, "  Hello   WORLD  "),
        _make_candidate(1, "hello world"),
        _make_candidate(2, "different"),
    ]

    result = strategy.aggregate(candidates)

    assert result.metadata == {"bucket_size": 2}
    assert result.chosen.index == 0


def test_majority_vote_uses_schema_for_json_matching() -> None:
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "score": {"type": "integer"},
        },
    }
    strategy = MajorityVoteStrategy(schema=schema)
    candidates = [
        _make_candidate(0, '{"score": 2, "answer": "agree"}'),
        _make_candidate(1, '{"answer": "agree", "score": 2}'),
        _make_candidate(2, '{"answer": "agree", "score": "2"}'),
    ]

    result = strategy.aggregate(candidates)

    assert result.metadata == {"bucket_size": 2}
    assert result.chosen.index in {0, 1}


def test_consensus_defaults_to_quorum_two() -> None:
    controller = AggregationController()
    config = RunnerConfig(mode="consensus")
    batch = [
        _make_result(0, "Alpha", latency=120, cost=0.2),
        _make_result(1, "Beta", latency=100, cost=0.1),
    ]

    selection = controller._select_aggregation(
        "consensus",
        config,
        batch,
        default_judge_config=None,
    )

    assert selection is None
    for _, result in batch:
        assert result.metrics.status == "error"
        assert result.metrics.failure_kind == "consensus_quorum"
        assert result.metrics.error_message and "quorum" in result.metrics.error_message


def test_auto_tie_breaker_latency_then_cost_then_order() -> None:
    controller = AggregationController()
    config = RunnerConfig(mode="consensus")
    batch = [
        _make_result(0, "Same", latency=200, cost=0.2),
        _make_result(1, "Same", latency=100, cost=0.4),
    ]
    lookup = {index: result for index, result in batch}
    breaker = controller._resolve_tie_breaker(
        config,
        lookup,
    )
    assert breaker is not None

    candidates = [
        AggregationCandidate(
            index=index,
            provider=f"provider-{index}",
            response=ProviderResponse(output_text="Same", latency_ms=lookup[index].metrics.latency_ms),
            text="Same",
        )
        for index in lookup
    ]

    choice = breaker.break_tie(candidates)
    assert choice.index == 1

    lookup[0].metrics.latency_ms = 100
    choice = breaker.break_tie(candidates)
    assert choice.index == 0

    lookup[1].metrics.cost_usd = 0.4
    lookup[0].metrics.cost_usd = 0.4
    choice = breaker.break_tie(candidates)
    assert choice.index == 0
