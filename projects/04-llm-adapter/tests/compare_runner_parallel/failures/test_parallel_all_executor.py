from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .helpers import _run_parallel_case

if TYPE_CHECKING:
    from tests.compare_runner_parallel.conftest import (
        ProviderConfigFactory,
        RunMetricsFactory,
        TaskFactory,
    )


def test_parallel_attempt_executor_parallel_all_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode="parallel_all",
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        run_metrics_factory=run_metrics_factory,
    )
    assert stop_reason == "all-done"
    results = dict(batch)
    assert results[1].stop_reason == "all-done"
    assert summaries == []


def test_parallel_attempt_executor_parallel_all_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode="parallel_all",
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        run_metrics_factory=run_metrics_factory,
    )
    assert stop_reason == "all-done"
    assert summaries == []
    assert [index for index, _ in batch] == [0, 1, 2]
    assert [result.metrics.status for _, result in batch] == ["ok", "ok", "ok"]
    assert [result.stop_reason for _, result in batch] == [None, "all-done", None]


def test_parallel_attempt_executor_parallel_all_failure_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    behaviours = {
        "parallel_all": {
            name: {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "boom",
            }
            for name in ("fail", "win", "tail")
        },
        "parallel_any": {name: {} for name in ("fail", "win", "tail")},
    }

    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode="parallel_all",
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        run_metrics_factory=run_metrics_factory,
        behaviours=behaviours,
    )
    assert stop_reason is None
    assert summaries == []
    assert [result.metrics.status for _, result in batch] == ["error", "error", "error"]
    assert [result.metrics.failure_kind for _, result in batch] == ["runtime", "runtime", "runtime"]
    assert all(result.stop_reason is None for _, result in batch)
