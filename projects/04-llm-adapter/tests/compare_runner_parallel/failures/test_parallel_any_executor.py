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


def test_parallel_attempt_executor_parallel_any_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode="parallel_any",
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        run_metrics_factory=run_metrics_factory,
    )
    assert stop_reason == "completed"
    results = dict(batch)
    assert results[2].metrics.failure_kind == "cancelled"
    assert summaries[0].backoff_next_provider is True
    assert summaries[0].error_type == "RuntimeError"


def test_parallel_attempt_executor_parallel_any_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode="parallel_any",
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        run_metrics_factory=run_metrics_factory,
    )
    assert stop_reason == "completed"
    assert [index for index, _ in batch] == [0, 1, 2]
    failure_result = dict(batch)[0]
    assert failure_result.metrics.status == "error"
    assert failure_result.metrics.failure_kind == "runtime"
    assert failure_result.metrics.error_message == "boom"
    assert failure_result.backoff_next_provider is True


def test_parallel_attempt_executor_parallel_any_failure_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    retries = {"fail": 2, "win": 3, "tail": 4}
    behaviours = {
        "parallel_any": {
            name: {
                "status": "error",
                "failure_kind": "runtime",
                "error_message": "fail",
                "retries": retries[name],
                "error": RuntimeError("fail"),
                "backoff": name == "fail",
            }
            for name in ("fail", "win", "tail")
        },
        "parallel_all": {name: {} for name in ("fail", "win", "tail")},
    }

    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode="parallel_any",
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        run_metrics_factory=run_metrics_factory,
        behaviours=behaviours,
    )
    assert stop_reason is None
    assert [result.metrics.status for _, result in batch] == ["error", "error", "error"]
    assert [result.metrics.error_message for _, result in batch] == ["fail", "fail", "fail"]
    assert [summary.provider for summary in summaries] == ["fail", "win", "tail"]
    assert [summary.retries for summary in summaries] == [2, 3, 4]
    assert all(summary.status == "error" for summary in summaries)
    assert all(summary.failure_kind == "runtime" for summary in summaries)
    assert all(summary.error_message == "fail" for summary in summaries)
    assert summaries[0].backoff_next_provider is True
    assert summaries[0].error_type == "RuntimeError"
