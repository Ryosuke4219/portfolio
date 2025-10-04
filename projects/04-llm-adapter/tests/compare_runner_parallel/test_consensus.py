from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from adapter.core.aggregation import AggregationCandidate, MajorityVoteStrategy
from adapter.core.aggregation_controller import AggregationController
from adapter.core.providers import BaseProvider, ProviderFactory, ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult
from adapter.core.runners import CompareRunner

if TYPE_CHECKING:
    from tests.compare_runner_parallel.conftest import (
        ProviderConfigFactory,
        RunMetricsFactory,
        TaskFactory,
    )


def _normalize_strategy(value: str | None) -> str | None:
    return "majority_vote" if value == "majority" else value


def _candidate(index: int, text: str) -> AggregationCandidate:
    return AggregationCandidate(
        index=index,
        provider=f"p{index}",
        response=ProviderResponse(output_text=text),
        text=text,
    )


def test_majority_vote_normalizes_text_variants() -> None:
    strategy = MajorityVoteStrategy()
    candidates = [
        _candidate(0, " Answer  With\tSpaces  "),
        _candidate(1, "answer with    spaces"),
        _candidate(2, "different"),
    ]

    result = strategy.aggregate(candidates)

    assert result.chosen.index == 0
    assert result.metadata == {"bucket_size": 2}
    assert result.tie_breaker_used == "stable_order"


def test_majority_vote_uses_json_equality_when_schema_present() -> None:
    strategy = MajorityVoteStrategy(schema={"type": "object"})
    candidates = [
        AggregationCandidate(
            index=0,
            provider="p1",
            response=ProviderResponse(output_text='{"value": 1, "items": [1, 2]}'),
            text='{"value": 1, "items": [1, 2]}',
        ),
        AggregationCandidate(
            index=1,
            provider="p2",
            response=ProviderResponse(output_text='{"items": [1,2], "value":1}'),
            text='{"items": [1,2], "value":1}',
        ),
        AggregationCandidate(
            index=2,
            provider="p3",
            response=ProviderResponse(output_text='{"value": 2}'),
            text='{"value": 2}',
        ),
    ]

    result = strategy.aggregate(candidates)

    assert result.metadata == {"bucket_size": 2}
    assert result.chosen.index in {0, 1}


def test_auto_tie_breaker_applies_latency_cost_and_order(
    run_metrics_factory: RunMetricsFactory,
) -> None:
    config = RunnerConfig(mode="consensus")
    candidates = [_candidate(0, "same"), _candidate(1, "same")]

    latency_lookup = {
        0: SingleRunResult(
            metrics=run_metrics_factory(provider="p1", model="m1", latency_ms=5, cost_usd=0.5),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=run_metrics_factory(provider="p2", model="m2", latency_ms=10, cost_usd=0.1),
            raw_output="same",
        ),
    }
    latency_breaker = AggregationController._resolve_tie_breaker(config, latency_lookup)
    assert latency_breaker and latency_breaker.break_tie(candidates).index == 0
    assert latency_breaker.name == "min_latency"

    cost_lookup = {
        0: SingleRunResult(
            metrics=run_metrics_factory(provider="p1", model="m1", latency_ms=5, cost_usd=0.4),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=run_metrics_factory(provider="p2", model="m2", latency_ms=5, cost_usd=0.1),
            raw_output="same",
        ),
    }
    cost_breaker = AggregationController._resolve_tie_breaker(config, cost_lookup)
    assert cost_breaker and cost_breaker.break_tie(candidates).index == 1
    assert cost_breaker.name == "min_cost"

    order_lookup = {
        0: SingleRunResult(
            metrics=run_metrics_factory(provider="p1", model="m1", latency_ms=5, cost_usd=0.1),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=run_metrics_factory(provider="p2", model="m2", latency_ms=5, cost_usd=0.1),
            raw_output="same",
        ),
    }
    order_breaker = AggregationController._resolve_tie_breaker(config, order_lookup)
    assert order_breaker and order_breaker.break_tie(candidates).index == 0
    assert order_breaker.name == "stable_order"


def _register_provider(monkeypatch: pytest.MonkeyPatch, name: str, cls: type[BaseProvider]) -> None:
    monkeypatch.setitem(ProviderFactory._registry, name, cls)


def _run_consensus(
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
    provider_specs: list[tuple[str, str, str]],
    *,
    metrics_name: str,
    task=None,
    **config_kwargs,
):
    configs = [
        provider_config_factory(tmp_path, name=name, provider=provider, model=model)
        for name, provider, model in provider_specs
    ]
    runner = CompareRunner(
        configs,
        [task or task_factory()],
        budget_manager_factory(),
        tmp_path / metrics_name,
    )
    return runner.run(repeat=1, config=RunnerConfig(mode="consensus", **config_kwargs))


def test_consensus_majority_and_judge_tiebreak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> None:
    class ConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text=self.config.model, input_tokens=1, output_tokens=1, latency_ms=5)

    _register_provider(monkeypatch, "consensus", ConsensusProvider)

    task = task_factory()
    results = _run_consensus(
        tmp_path,
        provider_config_factory,
        task_factory,
        budget_manager_factory,
        [
            ("c1", "consensus", "YES"),
            ("c2", "consensus", "YES"),
        ],
        metrics_name="metrics_consensus.jsonl",
        task=task,
        quorum=2,
    )
    winner = next(metric for metric in results if metric.ci_meta.get("aggregate_strategy"))
    assert winner.providers == ["consensus"]
    assert winner.token_usage == {"prompt": 1, "completion": 1, "total": 2}
    assert winner.retries == 0
    assert winner.outcome == "success"
    assert _normalize_strategy(winner.ci_meta["aggregate_strategy"]) == "majority_vote"
    assert winner.ci_meta["aggregate_votes"] == 2
    assert winner.ci_meta["aggregate_mode"] == "consensus"
    consensus_meta = winner.ci_meta["consensus"]
    assert _normalize_strategy(consensus_meta["strategy"]) == "majority_vote"
    assert consensus_meta["quorum"] == 2
    assert consensus_meta["votes"] == 2
    assert consensus_meta["chosen_provider"] == "consensus"
    assert consensus_meta.get("metadata", {}) == {"bucket_size": 2}

    class JudgeProvider(BaseProvider):
        calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            JudgeProvider.calls += 1
            return ProviderResponse(output_text="2", input_tokens=1, output_tokens=1, latency_ms=5)

    _register_provider(monkeypatch, "judge-consensus", JudgeProvider)

    judge_config = provider_config_factory(
        tmp_path, name="judge", provider="judge-consensus", model="judge-model"
    )
    tie_runner = CompareRunner(
        [
            provider_config_factory(tmp_path, name="t1", provider="consensus", model="A"),
            provider_config_factory(tmp_path, name="t2", provider="consensus", model="B"),
        ],
        [task],
        budget_manager_factory(),
        tmp_path / "metrics_judge.jsonl",
    )
    judge_results = tie_runner.run(
        repeat=1,
        config=RunnerConfig(mode="consensus", aggregate="judge", quorum=1, judge_provider=judge_config),
    )
    judge_winner = next(metric for metric in judge_results if metric.ci_meta.get("aggregate_strategy") == "judge")
    assert judge_winner.model == "B"
    assert JudgeProvider.calls == 1


