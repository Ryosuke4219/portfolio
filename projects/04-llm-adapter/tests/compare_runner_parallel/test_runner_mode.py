from __future__ import annotations

from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Sequence

import pytest

from adapter.core import errors
from adapter.core.metrics import RunMetrics
from adapter.core.runner_api import RunnerConfig
from adapter.core.runners import CompareRunner

if TYPE_CHECKING:
    from tests.compare_runner_parallel.conftest import ProviderConfigFactory, TaskFactory


def _normalize_mode(value: str) -> str:
    return value.replace("-", "_")


class _RunnerMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"


def test_compare_runner_normalizes_enum_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    budget_manager_factory,
) -> None:
    provider_config = provider_config_factory(tmp_path, name="p1", provider="p1", model="m1")
    runner = CompareRunner(
        provider_configs=[provider_config],
        tasks=[task_factory()],
        budget_manager=budget_manager_factory(),
        metrics_path=tmp_path / "metrics.jsonl",
    )
    config = RunnerConfig(mode=_RunnerMode.PARALLEL_ANY)
    captured = SimpleNamespace(aggregation=[], logs=[])

    def fake_apply(*, mode: str, config: RunnerConfig, batch, default_judge_config) -> None:  # type: ignore[override]
        captured.aggregation.append(mode)

    monkeypatch.setattr(runner._aggregation, "apply", fake_apply)

    def fake_log(mode: str, failures: Sequence[object]) -> None:
        captured.logs.append(mode)

    monkeypatch.setattr(runner, "_log_attempt_failures", fake_log)

    expected_error = errors.ParallelExecutionError

    def fake_run_tasks(**kwargs: object) -> list[RunMetrics]:  # type: ignore[override]
        aggregation_apply = kwargs["aggregation_apply"]
        record_failed_batch = kwargs["record_failed_batch"]
        log_attempt_failures = kwargs["log_attempt_failures"]
        parallel_execution_error = kwargs["parallel_execution_error"]
        aggregation_apply(mode=config.mode, config=config, batch=[], default_judge_config=None)
        record_failed_batch([], config, [[]])
        log_attempt_failures(config.mode, [SimpleNamespace(status="error")])
        assert parallel_execution_error is expected_error
        return []

    monkeypatch.setattr("adapter.core.runners.run_tasks", fake_run_tasks)

    results = runner.run(repeat=1, config=config)

    assert results == []
    assert [_normalize_mode(mode) for mode in captured.aggregation] == ["parallel_any", "parallel_any"]
    assert [_normalize_mode(mode) for mode in captured.logs] == ["parallel_any"]
