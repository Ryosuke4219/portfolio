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

from adapter.core.budgets import BudgetManager  # noqa: E402
from adapter.core.datasets import GoldenTask  # noqa: E402
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
