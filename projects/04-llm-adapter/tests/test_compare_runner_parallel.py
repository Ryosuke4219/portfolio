from __future__ import annotations

from pathlib import Path
import sys

import pytest

# Ensure shadow implementation modules are importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHADOW_ROOT = PROJECT_ROOT.parent / "04-llm-adapter-shadow"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if SHADOW_ROOT.exists() and str(SHADOW_ROOT) not in sys.path:
    sys.path.insert(0, str(SHADOW_ROOT))

from adapter.core.aggregation import (  # noqa: E402
    AggregationCandidate,
    MajorityVoteStrategy,
)
from adapter.core.aggregation_controller import AggregationController  # noqa: E402
from adapter.core.budgets import BudgetManager  # noqa: E402
from adapter.core.datasets import GoldenTask  # noqa: E402
from adapter.core.errors import TimeoutError  # noqa: E402
from adapter.core.metrics import RunMetrics  # noqa: E402
from adapter.core.models import (  # noqa: E402
    BudgetBook,
    BudgetRule,
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import (  # noqa: E402
    BaseProvider,
    ProviderFactory,
    ProviderResponse,
)
from adapter.core.runner_api import RunnerConfig  # noqa: E402
from adapter.core.runner_execution import SingleRunResult  # noqa: E402
from adapter.core.runners import CompareRunner  # noqa: E402


def _make_provider_config(
    tmp_path: Path, *, name: str, provider: str, model: str
) -> ProviderConfig:
    return ProviderConfig(
        path=tmp_path / f"{name}.yaml",
        schema_version=1,
        provider=provider,
        endpoint=None,
        model=model,
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


def _make_budget_manager() -> BudgetManager:
    book = BudgetBook(
        default=BudgetRule(
            run_budget_usd=10.0, daily_budget_usd=10.0, stop_on_budget_exceed=False
        ),
        overrides={},
    )
    return BudgetManager(book)


def _make_task() -> GoldenTask:
    return GoldenTask(
        task_id="t1",
        name="task",
        input={},
        prompt_template="prompt",
        expected={"type": "literal", "value": "YES"},
    )


def _make_run_metrics(
    *, provider: str, model: str, latency_ms: int, cost_usd: float
) -> RunMetrics:
    return RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id="run",
        provider=provider,
        model=model,
        mode="consensus",
        prompt_id="prompt-id",
        prompt_name="prompt",
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        input_tokens=1,
        output_tokens=1,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        status="ok",
        failure_kind=None,
        error_message=None,
        output_text="",
        output_hash=None,
    )


def test_majority_vote_normalizes_text_variants() -> None:
    strategy = MajorityVoteStrategy()
    candidates = [
        AggregationCandidate(
            index=0,
            provider="p1",
            response=ProviderResponse(output_text=" Answer  With\tSpaces  "),
            text=" Answer  With\tSpaces  ",
        ),
        AggregationCandidate(
            index=1,
            provider="p2",
            response=ProviderResponse(output_text="answer with    spaces"),
            text="answer with    spaces",
        ),
        AggregationCandidate(
            index=2,
            provider="p3",
            response=ProviderResponse(output_text="different"),
            text="different",
        ),
    ]

    result = strategy.aggregate(candidates)

    assert result.chosen.index == 0
    assert result.metadata == {"bucket_size": 2}
    assert result.tie_breaker_used == "first"


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


def test_auto_tie_breaker_applies_latency_cost_and_order() -> None:
    config = RunnerConfig(mode="consensus")
    base_candidates = [
        AggregationCandidate(
            index=0,
            provider="p1",
            response=ProviderResponse(output_text="same"),
            text="same",
        ),
        AggregationCandidate(
            index=1,
            provider="p2",
            response=ProviderResponse(output_text="same"),
            text="same",
        ),
    ]

    latency_lookup = {
        0: SingleRunResult(
            metrics=_make_run_metrics(provider="p1", model="m1", latency_ms=5, cost_usd=0.5),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=_make_run_metrics(provider="p2", model="m2", latency_ms=10, cost_usd=0.1),
            raw_output="same",
        ),
    }
    latency_breaker = AggregationController._resolve_tie_breaker(config, latency_lookup)
    assert latency_breaker is not None
    chosen_latency = latency_breaker.break_tie(base_candidates)
    assert chosen_latency.index == 0
    assert latency_breaker.name == "latency"

    cost_lookup = {
        0: SingleRunResult(
            metrics=_make_run_metrics(provider="p1", model="m1", latency_ms=5, cost_usd=0.4),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=_make_run_metrics(provider="p2", model="m2", latency_ms=5, cost_usd=0.1),
            raw_output="same",
        ),
    }
    cost_breaker = AggregationController._resolve_tie_breaker(config, cost_lookup)
    assert cost_breaker is not None
    chosen_cost = cost_breaker.break_tie(base_candidates)
    assert chosen_cost.index == 1
    assert cost_breaker.name == "cost"

    order_lookup = {
        0: SingleRunResult(
            metrics=_make_run_metrics(provider="p1", model="m1", latency_ms=5, cost_usd=0.1),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=_make_run_metrics(provider="p2", model="m2", latency_ms=5, cost_usd=0.1),
            raw_output="same",
        ),
    }
    order_breaker = AggregationController._resolve_tie_breaker(config, order_lookup)
    assert order_breaker is not None
    chosen_order = order_breaker.break_tie(base_candidates)
    assert chosen_order.index == 0
    assert order_breaker.name == "first"


def test_parallel_any_stops_after_first_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    class RecordingProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            calls.append(self.config.model)
            output = self.config.model
            return ProviderResponse(
                output_text=output,
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    monkeypatch.setitem(ProviderFactory._registry, "recording", RecordingProvider)

    fast_config = _make_provider_config(tmp_path, name="fast", provider="recording", model="fast")
    slow_config = _make_provider_config(tmp_path, name="slow", provider="recording", model="slow")

    from adapter.core import runners as runners_module

    def fake_run_parallel_any(workers, *, max_concurrency=None):  # type: ignore[override]
        return workers[0]()

    monkeypatch.setattr(runners_module, "run_parallel_any_sync", fake_run_parallel_any)

    runner = CompareRunner(
        [fast_config, slow_config],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_any.jsonl",
    )
    config = RunnerConfig(mode="parallel-any", max_concurrency=2)
    results = runner.run(repeat=1, config=config)
    assert {metric.model: metric.status for metric in results} == {
        "fast": "ok",
        "slow": "skip",
    }
    assert calls == ["fast"]


def test_parallel_any_cancels_pending_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import time

    class FastProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(
                output_text="fast",
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
            )

    class SlowProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            time.sleep(0.05)
            return ProviderResponse(
                output_text="slow",
                input_tokens=1,
                output_tokens=1,
                latency_ms=50,
            )

    monkeypatch.setitem(ProviderFactory._registry, "fast", FastProvider)
    monkeypatch.setitem(ProviderFactory._registry, "slow", SlowProvider)

    fast_config = _make_provider_config(
        tmp_path, name="fast", provider="fast", model="fast"
    )
    slow_config = _make_provider_config(
        tmp_path, name="slow", provider="slow", model="slow"
    )

    runner = CompareRunner(
        [fast_config, slow_config],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_cancel.jsonl",
    )
    results = runner.run(repeat=1, config=RunnerConfig(mode="parallel-any", max_concurrency=2))

    assert len(results) == 2
    status_by_model = {metric.model: metric.status for metric in results}
    assert status_by_model == {"fast": "ok", "slow": "skip"}

    slow_metric = next(metric for metric in results if metric.model == "slow")
    assert slow_metric.failure_kind == "cancelled"
    assert slow_metric.error_message == "parallel-any cancelled after winner"


def test_consensus_majority_and_judge_tiebreak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            output = self.config.model
            return ProviderResponse(
                output_text=output,
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    monkeypatch.setitem(ProviderFactory._registry, "consensus", ConsensusProvider)

    task = _make_task()
    metrics_path = tmp_path / "metrics_consensus.jsonl"
    runner = CompareRunner(
        [
            _make_provider_config(tmp_path, name="c1", provider="consensus", model="YES"),
            _make_provider_config(tmp_path, name="c2", provider="consensus", model="YES"),
        ],
        [task],
        _make_budget_manager(),
        metrics_path,
    )
    results = runner.run(repeat=1, config=RunnerConfig(mode="consensus", quorum=2))
    winner = next(metric for metric in results if metric.ci_meta.get("aggregate_strategy"))
    assert winner.providers == ["consensus"]
    assert winner.token_usage == {"prompt": 1, "completion": 1, "total": 2}
    assert winner.retries == 0
    assert winner.outcome == "success"
    assert winner.ci_meta["aggregate_strategy"] == "majority"
    assert winner.ci_meta["aggregate_votes"] == 2
    assert winner.ci_meta["aggregate_mode"] == "consensus"
    consensus_meta = winner.ci_meta["consensus"]
    assert consensus_meta["strategy"] == "majority"
    assert consensus_meta["quorum"] == 2
    assert consensus_meta["votes"] == 2
    assert consensus_meta["chosen_provider"] == "consensus"
    assert consensus_meta.get("metadata", {}) == {"bucket_size": 2}

    class JudgeProvider(BaseProvider):
        calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            JudgeProvider.calls += 1
            return ProviderResponse(
                output_text="2",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    monkeypatch.setitem(ProviderFactory._registry, "judge-consensus", JudgeProvider)

    judge_config = _make_provider_config(
        tmp_path, name="judge", provider="judge-consensus", model="judge-model"
    )
    tie_runner = CompareRunner(
        [
            _make_provider_config(tmp_path, name="t1", provider="consensus", model="A"),
            _make_provider_config(tmp_path, name="t2", provider="consensus", model="B"),
        ],
        [task],
        _make_budget_manager(),
        tmp_path / "metrics_judge.jsonl",
    )
    judge_config_instance = RunnerConfig(
        mode="consensus", aggregate="judge", quorum=1, judge_provider=judge_config
    )
    judge_results = tie_runner.run(repeat=1, config=judge_config_instance)
    judge_winner = next(
        metric for metric in judge_results if metric.ci_meta.get("aggregate_strategy") == "judge"
    )
    assert judge_winner.model == "B"
    assert JudgeProvider.calls == 1


def test_consensus_quorum_failure_marks_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(
                output_text="YES",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    monkeypatch.setitem(ProviderFactory._registry, "consensus", ConsensusProvider)

    runner = CompareRunner(
        [
            _make_provider_config(tmp_path, name="c1", provider="consensus", model="M1"),
            _make_provider_config(tmp_path, name="c2", provider="consensus", model="M2"),
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_quorum.jsonl",
    )
    config = RunnerConfig(mode="consensus", quorum=3)
    results = runner.run(repeat=2, config=config)
    assert len(results) == 4
    for metric in results:
        assert metric.status == "error"
        assert metric.failure_kind == "consensus_quorum"
        assert metric.error_message and "quorum" in metric.error_message
        assert "aggregate_strategy" not in metric.ci_meta
        assert metric.ci_meta["aggregate_mode"] == "consensus"
        assert metric.ci_meta["aggregate_quorum"] == 3
        assert metric.ci_meta["aggregate_votes"] == 2


def test_consensus_default_quorum_requires_two_votes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SplitConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            latency = 1 if self.config.model == "A" else 5
            return ProviderResponse(
                output_text=self.config.model,
                input_tokens=1,
                output_tokens=1,
                latency_ms=latency,
            )

    monkeypatch.setitem(ProviderFactory._registry, "split-consensus", SplitConsensusProvider)

    runner = CompareRunner(
        [
            _make_provider_config(
                tmp_path, name="p1", provider="split-consensus", model="A"
            ),
            _make_provider_config(
                tmp_path, name="p2", provider="split-consensus", model="B"
            ),
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_quorum_default.jsonl",
    )
    results = runner.run(repeat=1, config=RunnerConfig(mode="consensus"))
    assert len(results) == 2
    for metric in results:
        assert metric.status == "error"
        assert metric.failure_kind == "consensus_quorum"
        assert metric.ci_meta["aggregate_mode"] == "consensus"
        assert metric.ci_meta["aggregate_quorum"] == 2
        assert metric.ci_meta["aggregate_votes"] == 1
        assert "aggregate_strategy" not in metric.ci_meta


def test_runner_config_dataclass_initializes_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_bucket_args: list[int | None] = []
    schema_args: list[Path | None] = []

    class RecordingTokenBucket:
        def __init__(self, rpm: int | None) -> None:
            token_bucket_args.append(rpm)

        def acquire(self) -> None:
            return None

    class RecordingSchemaValidator:
        def __init__(self, schema: Path | None) -> None:
            schema_args.append(schema)

        def validate(self, payload: str) -> None:
            return None

    from adapter.core import runners as runners_module

    monkeypatch.setattr(runners_module, "_TokenBucket", RecordingTokenBucket)
    monkeypatch.setattr(runners_module, "_SchemaValidator", RecordingSchemaValidator)

    class SingleCallProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(
                output_text="ok",
                input_tokens=1,
                output_tokens=1,
                latency_ms=1,
            )

    monkeypatch.setitem(ProviderFactory._registry, "single", SingleCallProvider)

    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    runner = CompareRunner(
        [
            _make_provider_config(
                tmp_path, name="single", provider="single", model="model"
            )
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_helpers.jsonl",
    )
    config = RunnerConfig(mode="sequential", rpm=3, schema=schema_path)

    runner.run(repeat=1, config=config)

    assert token_bucket_args == [3]
    assert schema_args == [schema_path]


def test_run_metrics_records_error_type_and_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FlakyProvider(BaseProvider):
        def __init__(self, config: ProviderConfig) -> None:
            super().__init__(config)
            self.calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("boom")
            return ProviderResponse(
                output_text="flaky-ok",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    class StableProvider(BaseProvider):
        def __init__(self, config: ProviderConfig) -> None:
            super().__init__(config)

        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(
                output_text="stable-ok",
                input_tokens=1,
                output_tokens=1,
                latency_ms=2,
            )

    monkeypatch.setitem(ProviderFactory._registry, "flaky", FlakyProvider)
    monkeypatch.setitem(ProviderFactory._registry, "stable", StableProvider)

    runner = CompareRunner(
        [
            _make_provider_config(tmp_path, name="flaky", provider="flaky", model="F"),
            _make_provider_config(tmp_path, name="stable", provider="stable", model="S"),
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_attempts.jsonl",
    )
    results = runner.run(repeat=2, config=RunnerConfig(mode="parallel-all"))

    flaky_attempts = {metric.attempts: metric for metric in results if metric.provider == "flaky"}
    stable_attempts = sorted(
        (metric.attempts, metric.error_type)
        for metric in results
        if metric.provider == "stable"
    )

    assert flaky_attempts[1].status == "error"
    assert flaky_attempts[1].error_type == "TimeoutError"
    assert flaky_attempts[2].status == "ok"
    assert flaky_attempts[2].error_type is None
    assert stable_attempts == [(1, None), (2, None)]
