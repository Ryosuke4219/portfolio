from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import cast

import pytest

# Ensure shadow implementation modules are importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHADOW_ROOT = PROJECT_ROOT.parent / "04-llm-adapter-shadow"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if SHADOW_ROOT.exists() and str(SHADOW_ROOT) not in sys.path:
    sys.path.insert(0, str(SHADOW_ROOT))

from adapter.core import errors  # noqa: E402
from adapter.core.aggregation import (  # noqa: E402
    AggregationCandidate,
    MajorityVoteStrategy,
)
from adapter.core.aggregation_controller import AggregationController  # noqa: E402
from adapter.core.budgets import BudgetManager  # noqa: E402
from adapter.core.datasets import GoldenTask  # noqa: E402
from adapter.core.errors import ProviderSkip, TimeoutError  # noqa: E402
from adapter.core.metrics import BudgetSnapshot, RunMetrics  # noqa: E402
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
from adapter.core.runner_execution import RunnerExecution, SingleRunResult  # noqa: E402
from adapter.core.runner_execution_parallel import (  # noqa: E402
    ParallelAttemptExecutor,
    ProviderFailureSummary,
)
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


def _normalize_mode(value: str) -> str:
    return value.replace("-", "_")


def _normalize_strategy(value: str | None) -> str | None:
    if value == "majority":
        return "majority_vote"
    return value


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
            metrics=_make_run_metrics(
                provider="p1", model="m1", latency_ms=5, cost_usd=0.5
            ),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=_make_run_metrics(
                provider="p2", model="m2", latency_ms=10, cost_usd=0.1
            ),
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
            metrics=_make_run_metrics(
                provider="p1", model="m1", latency_ms=5, cost_usd=0.4
            ),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=_make_run_metrics(
                provider="p2", model="m2", latency_ms=5, cost_usd=0.1
            ),
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
            metrics=_make_run_metrics(
                provider="p1", model="m1", latency_ms=5, cost_usd=0.1
            ),
            raw_output="same",
        ),
        1: SingleRunResult(
            metrics=_make_run_metrics(
                provider="p2", model="m2", latency_ms=5, cost_usd=0.1
            ),
            raw_output="same",
        ),
    }
    order_breaker = AggregationController._resolve_tie_breaker(config, order_lookup)
    assert order_breaker is not None
    chosen_order = order_breaker.break_tie(base_candidates)
    assert chosen_order.index == 0
    assert order_breaker.name == "stable_order"


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

    fast_config = _make_provider_config(
        tmp_path, name="fast", provider="recording", model="fast"
    )
    slow_config = _make_provider_config(
        tmp_path, name="slow", provider="recording", model="slow"
    )

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
    config = RunnerConfig(mode="parallel_any", max_concurrency=2)
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
    results = runner.run(
        repeat=1, config=RunnerConfig(mode="parallel_any", max_concurrency=2)
    )

    assert len(results) == 2
    status_by_model = {metric.model: metric.status for metric in results}
    assert status_by_model == {"fast": "ok", "slow": "skip"}

    slow_metric = next(metric for metric in results if metric.model == "slow")
    assert slow_metric.failure_kind == "cancelled"
    assert _normalize_mode(slow_metric.error_message) == "parallel_any cancelled after winner"


def test_parallel_any_populates_metrics_for_unscheduled_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class WinnerProvider(BaseProvider):
        calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            WinnerProvider.calls += 1
            return ProviderResponse(
                output_text="winner",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    class IdleProvider(BaseProvider):
        called = False

        def generate(
            self, prompt: str
        ) -> ProviderResponse:  # pragma: no cover - 防御ライン
            IdleProvider.called = True
            raise AssertionError("idle provider should not run")

    monkeypatch.setitem(ProviderFactory._registry, "winner", WinnerProvider)
    monkeypatch.setitem(ProviderFactory._registry, "idle", IdleProvider)

    winner_config = _make_provider_config(
        tmp_path, name="winner", provider="winner", model="winner"
    )
    idle_config = _make_provider_config(
        tmp_path, name="idle", provider="idle", model="idle"
    )

    from adapter.core import runners as runners_module

    def fake_run_parallel_any(workers, *, max_concurrency=None):  # type: ignore[override]
        return workers[0]()

    monkeypatch.setattr(runners_module, "run_parallel_any_sync", fake_run_parallel_any)

    runner = CompareRunner(
        [winner_config, idle_config],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_unscheduled.jsonl",
    )
    results = runner.run(
        repeat=1, config=RunnerConfig(mode="parallel_any", max_concurrency=2)
    )

    metrics_by_model = {metric.model: metric for metric in results}
    assert WinnerProvider.calls == 1
    assert IdleProvider.called is False

    idle_metrics = metrics_by_model["idle"]
    assert idle_metrics.status == "skip"
    assert idle_metrics.failure_kind == "cancelled"
    assert _normalize_mode(idle_metrics.error_message) == "parallel_any cancelled after winner"
    assert idle_metrics.input_tokens == 0
    assert idle_metrics.output_tokens == 0
    assert idle_metrics.latency_ms == 0
    assert idle_metrics.cost_usd == 0.0


def test_parallel_any_failure_summary_includes_all_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SkipProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            raise ProviderSkip("skip me")

    class TimeoutProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            raise TimeoutError("deadline")

    monkeypatch.setitem(ProviderFactory._registry, "skip", SkipProvider)
    monkeypatch.setitem(ProviderFactory._registry, "timeout", TimeoutProvider)

    skip_config = _make_provider_config(
        tmp_path, name="skip", provider="skip", model="skip-model"
    )
    timeout_config = _make_provider_config(
        tmp_path, name="timeout", provider="timeout", model="timeout-model"
    )

    runner = CompareRunner(
        [skip_config, timeout_config],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_failure_summary.jsonl",
    )

    with pytest.raises(errors.ParallelExecutionError) as exc_info:
        runner.run(
            repeat=1, config=RunnerConfig(mode="parallel_any", max_concurrency=2)
        )

    failures = getattr(exc_info.value, "failures", ())
    assert len(failures) == 2
    summary_by_provider = {failure.provider: failure for failure in failures}

    skip_summary = summary_by_provider["skip"]
    assert skip_summary.status == "skip"
    assert skip_summary.failure_kind == "skip"
    assert skip_summary.error_message == "skip me"
    assert skip_summary.backoff_next_provider is True
    assert skip_summary.retries == 0
    assert skip_summary.error_type == "ProviderSkip"

    timeout_summary = summary_by_provider["timeout"]
    assert timeout_summary.status == "error"
    assert timeout_summary.failure_kind == "timeout"
    assert timeout_summary.error_message == "deadline"
    assert timeout_summary.backoff_next_provider is False
    assert timeout_summary.retries == 0
    assert timeout_summary.error_type == "TimeoutError"


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
            _make_provider_config(
                tmp_path, name="c1", provider="consensus", model="YES"
            ),
            _make_provider_config(
                tmp_path, name="c2", provider="consensus", model="YES"
            ),
        ],
        [task],
        _make_budget_manager(),
        metrics_path,
    )
    results = runner.run(repeat=1, config=RunnerConfig(mode="consensus", quorum=2))
    winner = next(
        metric for metric in results if metric.ci_meta.get("aggregate_strategy")
    )
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
        metric
        for metric in judge_results
        if metric.ci_meta.get("aggregate_strategy") == "judge"
    )
    assert judge_winner.model == "B"
    assert JudgeProvider.calls == 1


def test_consensus_default_quorum_meta_uses_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ThreeWayConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(
                output_text="YES",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    monkeypatch.setitem(
        ProviderFactory._registry, "three-way-consensus", ThreeWayConsensusProvider
    )

    runner = CompareRunner(
        [
            _make_provider_config(
                tmp_path, name="p1", provider="three-way-consensus", model="YES"
            ),
            _make_provider_config(
                tmp_path, name="p2", provider="three-way-consensus", model="YES"
            ),
            _make_provider_config(
                tmp_path, name="p3", provider="three-way-consensus", model="YES"
            ),
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_consensus_quorum_default.jsonl",
    )

    results = runner.run(repeat=1, config=RunnerConfig(mode="consensus"))
    winner = next(metric for metric in results if metric.ci_meta.get("consensus"))

    consensus_meta = winner.ci_meta["consensus"]
    assert consensus_meta["quorum"] == 2
    assert winner.ci_meta["aggregate_quorum"] == 2


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
            _make_provider_config(
                tmp_path, name="c1", provider="consensus", model="M1"
            ),
            _make_provider_config(
                tmp_path, name="c2", provider="consensus", model="M2"
            ),
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


def test_consensus_quorum_falls_back_to_judge(
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

    class JudgeProvider(BaseProvider):
        calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            JudgeProvider.calls += 1
            return ProviderResponse(
                output_text="JUDGE",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    monkeypatch.setitem(ProviderFactory._registry, "consensus", ConsensusProvider)
    monkeypatch.setitem(ProviderFactory._registry, "judge-consensus", JudgeProvider)

    judge_config = _make_provider_config(
        tmp_path, name="judge", provider="judge-consensus", model="judge-model"
    )
    runner = CompareRunner(
        [
            _make_provider_config(tmp_path, name="c1", provider="consensus", model="A"),
            _make_provider_config(tmp_path, name="c2", provider="consensus", model="A"),
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_consensus_quorum_fallback.jsonl",
    )

    results = runner.run(
        repeat=1,
        config=RunnerConfig(mode="consensus", quorum=3, judge_provider=judge_config),
    )

    winner = next(
        metric
        for metric in results
        if metric.ci_meta.get("aggregate_strategy") == "judge"
    )

    assert winner.status == "ok"
    assert winner.failure_kind is None
    assert winner.ci_meta["aggregate_mode"] == "consensus"
    assert winner.ci_meta["aggregate_quorum"] == 3
    assert winner.ci_meta["consensus"]["fallback"] == "judge"
    assert JudgeProvider.calls == 1
    assert all(metric.failure_kind != "consensus_quorum" for metric in results)


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

    monkeypatch.setitem(
        ProviderFactory._registry, "split-consensus", SplitConsensusProvider
    )

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
            _make_provider_config(
                tmp_path, name="stable", provider="stable", model="S"
            ),
        ],
        [_make_task()],
        _make_budget_manager(),
        tmp_path / "metrics_attempts.jsonl",
    )
    results = runner.run(repeat=2, config=RunnerConfig(mode="parallel_all"))

    flaky_attempts = {
        metric.attempts: metric for metric in results if metric.provider == "flaky"
    }
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


def _run_parallel_all_sync(
    workers: Sequence[Callable[[], int]], *, max_concurrency: int | None = None
) -> list[int]:
    return [worker() for worker in workers]


def _run_parallel_any_sync(
    workers: Sequence[Callable[[], int]], *, max_concurrency: int | None = None
) -> int:
    winner: int | None = None
    last_error: BaseException | None = None
    for worker in workers:
        try:
            idx = worker()
        except BaseException as exc:  # noqa: BLE001
            last_error = exc
        else:
            if winner is None:
                winner = idx
    if winner is not None:
        return winner
    raise RuntimeError("parallel_any failed") from last_error


def _run_parallel_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    behaviours: dict[str, dict[str, dict[str, object]]] | None = None,
) -> tuple[list[tuple[int, SingleRunResult]], list[ProviderFailureSummary], str | None]:
    from adapter.core.runner_execution_parallel import ParallelAnyState

    task = _make_task()
    providers = [
        _make_provider_config(tmp_path, name=n, provider=n, model=n)
        for n in ("fail", "win", "tail")
    ]
    summaries: list[ProviderFailureSummary] = []
    if mode == "parallel_any":

        def _record(
            self: ParallelAnyState, index: int, summary: ProviderFailureSummary
        ) -> None:
            summaries.append(summary)
            ParallelAnyState.register_failure(self, index, summary)

        monkeypatch.setattr(
            "adapter.core.runner_execution_parallel.ParallelAnyState",
            type("RecordingState", (ParallelAnyState,), {"register_failure": _record}),
        )
    state_factory = sys.modules[
        "adapter.core.runner_execution_parallel"
    ].ParallelAnyState
    behaviour_map = behaviours or {
        "parallel_any": {
            "fail": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "boom",
                "retries": 1,
                "error": RuntimeError("boom"),
                "backoff": True,
            },
            "win": {"stop": "completed"},
            "tail": {},
        },
        "parallel_all": {
            "fail": {},
            "win": {"stop": "all-done"},
            "tail": {},
        },
    }

    def run_single(
        config: ProviderConfig,
        _provider: object,
        _task: GoldenTask,
        _attempt: int,
        _mode: str,
    ) -> SingleRunResult:
        metrics = _make_run_metrics(
            provider=config.provider, model=config.model, latency_ms=0, cost_usd=0.0
        )
        data = behaviour_map[mode][config.provider]
        status = data.get("status")
        if isinstance(status, str):
            metrics.status = status
        failure_kind = data.get("failure_kind")
        if isinstance(failure_kind, str):
            metrics.failure_kind = failure_kind
        message = data.get("error_message")
        if isinstance(message, str):
            metrics.error_message = message
        retries = data.get("retries")
        if isinstance(retries, int):
            metrics.retries = retries
        return SingleRunResult(
            metrics=metrics,
            raw_output=config.provider,
            stop_reason=data.get("stop") if isinstance(data.get("stop"), str) else None,
            error=(
                data.get("error") if isinstance(data.get("error"), Exception) else None
            ),
            backoff_next_provider=bool(data.get("backoff", False)),
        )

    executor = ParallelAttemptExecutor(
        run_single,
        lambda total, limit: total,
        run_parallel_all_sync=_run_parallel_all_sync,
        run_parallel_any_sync=_run_parallel_any_sync,
        parallel_execution_error=RuntimeError,
        parallel_any_state_factory=state_factory,
    )
    try:
        batch, stop_reason = executor.run(
            [(cfg, cast(BaseProvider, object())) for cfg in providers],
            task,
            attempt_index=0,
            config=RunnerConfig(mode=mode),
        )
    except RuntimeError as exc:  # pragma: no cover - parallel_any failure path
        error_batch = getattr(exc, "batch", [])
        error_failures = getattr(exc, "failures", [])
        if not summaries and error_failures:
            summaries.extend(error_failures)
        return list(error_batch), summaries, None
    return list(batch), summaries, stop_reason


@pytest.mark.parametrize(
    ("mode", "expected_stop"),
    [("parallel_any", "completed"), ("parallel_all", "all-done")],
)
def test_parallel_executor_parallel_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, expected_stop: str
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(tmp_path, monkeypatch, mode)
    assert stop_reason == expected_stop
    results = dict(batch)
    if mode == "parallel_any":
        assert results[2].metrics.failure_kind == "cancelled"
        assert summaries[0].backoff_next_provider is True
        assert summaries[0].error_type == "RuntimeError"
    else:
        assert results[1].stop_reason == expected_stop


def test_parallel_attempt_executor_parallel_all_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path, monkeypatch, mode="parallel_all"
    )

    assert stop_reason == "all-done"
    assert summaries == []
    assert [index for index, _ in batch] == [0, 1, 2]

    assert [result.metrics.status for _, result in batch] == ["ok", "ok", "ok"]
    assert [result.stop_reason for _, result in batch] == [None, "all-done", None]


def test_parallel_attempt_executor_parallel_all_failure_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    behaviours = {
        "parallel_all": {
            "fail": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "boom",  # noqa: S106 - テスト入力
            },
            "win": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "boom",  # noqa: S106 - テスト入力
            },
            "tail": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "boom",  # noqa: S106 - テスト入力
            },
        },
        "parallel_any": {
            "fail": {},
            "win": {},
            "tail": {},
        },
    }

    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path, monkeypatch, mode="parallel_all", behaviours=behaviours
    )

    assert stop_reason is None
    assert summaries == []
    assert [result.metrics.status for _, result in batch] == ["error", "error", "error"]
    assert [result.metrics.failure_kind for _, result in batch] == [
        "runtime",
        "runtime",
        "runtime",
    ]
    assert all(result.stop_reason is None for _, result in batch)


def test_parallel_attempt_executor_parallel_any_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path, monkeypatch, mode="parallel_any"
    )

    assert stop_reason == "completed"
    assert [index for index, _ in batch] == [0, 1, 2]

    failure_result = dict(batch)[0]
    assert failure_result.metrics.status == "error"
    assert failure_result.metrics.failure_kind == "runtime"
    assert failure_result.metrics.error_message == "boom"
    assert failure_result.backoff_next_provider is True

    assert [summary.provider for summary in summaries] == ["fail"]
    assert summaries[0].status == "error"
    assert summaries[0].failure_kind == "runtime"
    assert summaries[0].error_message == "boom"
    assert summaries[0].backoff_next_provider is True
    assert summaries[0].retries == 1
    assert summaries[0].error_type == "RuntimeError"


def test_parallel_attempt_executor_parallel_any_failure_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    behaviours = {
        "parallel_any": {
            "fail": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "fail",  # noqa: S106 - テスト入力
                "retries": 2,
                "error": RuntimeError("fail"),
                "backoff": True,
            },
            "win": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "fail",  # noqa: S106 - テスト入力
                "retries": 3,
                "error": RuntimeError("fail"),
            },
            "tail": {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "fail",  # noqa: S106 - テスト入力
                "retries": 4,
                "error": RuntimeError("fail"),
            },
        },
        "parallel_all": {
            "fail": {},
            "win": {},
            "tail": {},
        },
    }

    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path, monkeypatch, mode="parallel_any", behaviours=behaviours
    )

    assert stop_reason is None
    assert [result.metrics.status for _, result in batch] == ["error", "error", "error"]
    assert [result.metrics.error_message for _, result in batch] == [
        "fail",
        "fail",
        "fail",
    ]

    assert [summary.provider for summary in summaries] == ["fail", "win", "tail"]
    assert [summary.retries for summary in summaries] == [2, 3, 4]
    assert all(summary.status == "error" for summary in summaries)
    assert all(summary.failure_kind == "runtime" for summary in summaries)
    assert all(summary.error_message == "fail" for summary in summaries)
    assert summaries[0].backoff_next_provider is True
    assert summaries[0].error_type == "RuntimeError"


class _RunnerMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"


def test_compare_runner_normalizes_enum_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_config = _make_provider_config(
        tmp_path, name="p1", provider="p1", model="m1"
    )
    runner = CompareRunner(
        provider_configs=[provider_config],
        tasks=[_make_task()],
        budget_manager=_make_budget_manager(),
        metrics_path=tmp_path / "metrics.jsonl",
    )
    config = RunnerConfig(mode=_RunnerMode.PARALLEL_ANY)
    captured = SimpleNamespace(aggregation=[], logs=[])

    def fake_apply(
        *,
        mode: str,
        config: RunnerConfig,
        batch: Sequence[tuple[int, SingleRunResult]],
        default_judge_config: ProviderConfig | None,
    ) -> None:
        captured.aggregation.append(mode)

    monkeypatch.setattr(runner._aggregation, "apply", fake_apply)

    def fake_log(mode: str, failures: Sequence[object]) -> None:
        captured.logs.append(mode)

    monkeypatch.setattr(runner, "_log_attempt_failures", fake_log)

    expected_error = errors.ParallelExecutionError

    def fake_run_tasks(
        *,
        aggregation_apply: Callable[..., None],
        record_failed_batch: Callable[..., None],
        log_attempt_failures: Callable[[object, Sequence[object]], None],
        parallel_execution_error: type[Exception],
        **_: object,
    ) -> list[RunMetrics]:
        aggregation_apply(
            mode=config.mode,
            config=config,
            batch=[],
            default_judge_config=None,
        )
        record_failed_batch([], config, [[]])
        log_attempt_failures(config.mode, [SimpleNamespace(status="error")])
        assert parallel_execution_error is expected_error
        return []

    monkeypatch.setattr("adapter.core.runners.run_tasks", fake_run_tasks)

    results = runner.run(repeat=1, config=config)

    assert results == []
    assert [_normalize_mode(mode) for mode in captured.aggregation] == [
        "parallel_any",
        "parallel_any",
    ]
    assert [_normalize_mode(mode) for mode in captured.logs] == ["parallel_any"]
