from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapter.core.budgets import BudgetBook, BudgetManager, BudgetRule
from adapter.core.config import ProviderConfig
from adapter.core.datasets import GoldenTask
from adapter.core.models import PricingConfig, QualityGatesConfig, RateLimitConfig, RetryConfig
from adapter.core.runner_api import BackoffPolicy, RunnerConfig
from adapter.core.runners import CompareRunner


class _StubRunnerExecution:
    plan: dict[tuple[str, int], tuple[list[tuple[int, SimpleNamespace]], str | None]]

    def __init__(self, **_: object) -> None:
        self.calls: list[tuple[str, int]] = []

    def run_parallel_attempt(
        self,
        providers: object,
        task: GoldenTask,
        attempt: int,
        config: RunnerConfig,
    ) -> tuple[list[tuple[int, SimpleNamespace]], str | None]:
        self.calls.append((task.task_id, attempt))
        return self.plan[(task.task_id, attempt)]

    def run_sequential_attempt(
        self,
        providers: object,
        task: GoldenTask,
        attempt: int,
        mode: str,
    ) -> tuple[list[tuple[int, SimpleNamespace]], str | None]:
        return self.run_parallel_attempt(providers, task, attempt, RunnerConfig(mode=mode))


@pytest.fixture(name="budget_manager")
def _budget_manager() -> BudgetManager:
    rule = BudgetRule(run_budget_usd=10.0, daily_budget_usd=100.0, stop_on_budget_exceed=False)
    book = BudgetBook(default=rule, overrides={})
    return BudgetManager(book)


@pytest.fixture(name="provider_config")
def _provider_config(tmp_path_factory: pytest.TempPathFactory) -> ProviderConfig:
    base_dir = tmp_path_factory.mktemp("provider")
    base_path = base_dir / "config.yaml"
    base_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=base_path,
        schema_version=1,
        provider="mock",
        endpoint=None,
        model="test-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=30,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


@pytest.fixture(name="runner_config")
def _runner_config(tmp_path_factory: pytest.TempPathFactory) -> RunnerConfig:
    metrics_dir = tmp_path_factory.mktemp("metrics")
    metrics_path = metrics_dir / "runs.jsonl"
    return RunnerConfig(
        mode="parallel-any",
        metrics_path=metrics_path,
        backoff=BackoffPolicy(),
    )


def test_compare_runner_orchestrates_aggregation_and_finalization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    budget_manager: BudgetManager,
    provider_config: ProviderConfig,
    runner_config: RunnerConfig,
) -> None:
    tasks = [
        GoldenTask(task_id="task-a", name="A", input={}, prompt_template="", expected={}),
        GoldenTask(task_id="task-b", name="B", input={}, prompt_template="", expected={}),
    ]
    runner = CompareRunner(
        provider_configs=[provider_config],
        tasks=tasks,
        budget_manager=budget_manager,
        metrics_path=tmp_path_factory.mktemp("metrics_out") / "runs.jsonl",
    )

    plan = {
        ("task-a", 0): ([(0, SimpleNamespace(raw_output="a0", metrics=SimpleNamespace()))], None),
        ("task-a", 1): ([(0, SimpleNamespace(raw_output="a1", metrics=SimpleNamespace()))], None),
        ("task-b", 0): ([(0, SimpleNamespace(raw_output="b0", metrics=SimpleNamespace()))], None),
        ("task-b", 1): ([(0, SimpleNamespace(raw_output="b1", metrics=SimpleNamespace()))], "stop"),
    }
    _StubRunnerExecution.plan = plan

    monkeypatch.setattr(
        "adapter.core.runners.RunnerExecution",
        lambda **kwargs: _StubRunnerExecution(**kwargs),
    )

    provider_instance = SimpleNamespace()
    monkeypatch.setattr(
        "adapter.core.execution.compare_task_runner.ProviderFactory.create",
        lambda cfg: provider_instance,
    )

    aggregation_calls = MagicMock()
    finalize_calls = MagicMock()
    monkeypatch.setattr(runner._aggregation, "apply", aggregation_calls)
    monkeypatch.setattr(runner._task_finalizer, "finalize_task", finalize_calls)

    results = runner.run(repeat=2, config=runner_config)

    assert aggregation_calls.call_count == 4
    assert finalize_calls.call_count == 2
    assert [call.args[0] for call in finalize_calls.call_args_list] == tasks[:2]
    assert results == []
