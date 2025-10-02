from __future__ import annotations

from enum import Enum
from typing import cast

import pytest

from adapter.core.metrics import RunMetrics
from adapter.core.providers import BaseProvider
from adapter.core.runner_execution import SingleRunResult
from adapter.core.runner_execution_parallel import _ParallelCoordinatorBase

try:  # pragma: no cover - 型補完と後方互換用
    from adapter.core.runner_api import RunnerConfig, RunnerMode
except ImportError:  # pragma: no cover - RunnerMode 未導入環境向け
    from adapter.core.runner_api import RunnerConfig

    class RunnerMode(str, Enum):  # type: ignore[misc]
        PARALLEL_ANY = "parallel_any"

# 並列実行戦略
def test_parallel_any_success_marks_failures_and_cancellations(
    make_provider_config,
    golden_task,
    make_run_metrics,
    make_parallel_executor,
    parallel_any_value,
) -> None:
    providers = [
        make_provider_config("failure"),
        make_provider_config("winner"),
        make_provider_config("cancelled"),
    ]
    failure_error = RuntimeError("boom")

    def run_single(config, _provider, _task, _attempt, mode):
        assert mode == parallel_any_value
        if config.provider == "failure":
            metrics = make_run_metrics(
                config,
                status="error",
                failure_kind="runtime",
                error_message="boom",
            )
            metrics.retries = 2
            return SingleRunResult(
                metrics=metrics,
                raw_output="",
                stop_reason=None,
                error=failure_error,
                backoff_next_provider=True,
            )
        metrics = make_run_metrics(
            config,
            status="ok",
            failure_kind=None,
            error_message=None,
        )
        return SingleRunResult(
            metrics=metrics,
            raw_output="ok",
            stop_reason="completed",
        )

    executor = make_parallel_executor(run_single)
    provider_pairs = [(cfg, cast(BaseProvider, object())) for cfg in providers]
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ANY)

    batch, stop_reason = executor.run(provider_pairs, golden_task, attempt_index=0, config=config)

    assert stop_reason == "completed"
    assert len(batch) == 3
    results = {index: result for index, result in batch}

    failure_result = results[0]
    assert failure_result.metrics.status == "error"
    assert failure_result.metrics.failure_kind == "runtime"
    assert failure_result.metrics.error_message == "boom"
    assert failure_result.backoff_next_provider is True
    assert failure_result.error is failure_error

    winner_result = results[1]
    assert winner_result.metrics.status == "ok"
    assert winner_result.stop_reason == "completed"

    cancelled_result = results[2]
    assert cancelled_result.metrics.status == "skip"
    assert cancelled_result.metrics.failure_kind == "cancelled"
    assert cancelled_result.metrics.error_message == _ParallelCoordinatorBase.CANCEL_MESSAGE
    assert cancelled_result.stop_reason == "cancelled"


def test_parallel_any_all_failures_raise_parallel_error(
    make_provider_config,
    golden_task,
    make_run_metrics,
    make_parallel_executor,
    parallel_any_value,
    parallel_execution_error,
) -> None:
    providers = [
        make_provider_config("first"),
        make_provider_config("second"),
    ]

    def run_single(config, _provider, _task, _attempt, mode):
        assert mode == parallel_any_value
        metrics = make_run_metrics(
            config,
            status="error",
            failure_kind="runtime",
            error_message=f"{config.provider}-failed",
        )
        metrics.retries = 1
        return SingleRunResult(
            metrics=metrics,
            raw_output="",
            error=ValueError(config.provider),
        )

    executor = make_parallel_executor(run_single)
    provider_pairs = [(cfg, cast(BaseProvider, object())) for cfg in providers]
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ANY)

    with pytest.raises(parallel_execution_error) as excinfo:
        executor.run(provider_pairs, golden_task, attempt_index=0, config=config)

    error = excinfo.value
    assert isinstance(error.failures, list)
    assert len(error.failures) == 2
    assert {summary.provider for summary in error.failures} == {"first", "second"}
    first_summary = next(summary for summary in error.failures if summary.provider == "first")
    assert first_summary.failure_kind == "runtime"
    assert first_summary.error_message == "first-failed"
    assert first_summary.error_type == "ValueError"
    assert first_summary.backoff_next_provider is False
    assert first_summary.retries == 1

    assert isinstance(error.batch, list)
    assert len(error.batch) == 2
    assert all(isinstance(result.metrics, RunMetrics) for _, result in error.batch)


def test_parallel_any_mode_accepts_hyphen_compatibility(
    make_provider_config,
    golden_task,
    make_run_metrics,
    make_parallel_executor,
    parallel_any_value,
) -> None:
    providers = [make_provider_config("winner")]
    observed_modes: list[str] = []

    def run_single(config, _provider, _task, _attempt, mode):
        observed_modes.append(mode)
        metrics = make_run_metrics(
            config,
            status="ok",
            failure_kind=None,
            error_message=None,
        )
        return SingleRunResult(
            metrics=metrics,
            raw_output="ok",
            stop_reason="completed",
        )

    executor = make_parallel_executor(run_single)
    provider_pairs = [(cfg, cast(BaseProvider, object())) for cfg in providers]
    config = RunnerConfig(mode="parallel-any")

    batch, stop_reason = executor.run(provider_pairs, golden_task, attempt_index=0, config=config)

    assert observed_modes == [parallel_any_value]
    assert stop_reason == "completed"
    assert len(batch) == 1
    index, result = batch[0]
    assert index == 0
    assert result.raw_output == "ok"
