from __future__ import annotations

from enum import Enum
from typing import cast

from adapter.core.providers import BaseProvider
from adapter.core.runner_execution import SingleRunResult

try:  # pragma: no cover - 型補完と後方互換用
    from adapter.core.runner_api import RunnerConfig, RunnerMode
except ImportError:  # pragma: no cover - RunnerMode 未導入環境向け
    from adapter.core.runner_api import RunnerConfig

    class RunnerMode(str, Enum):  # type: ignore[misc]
        PARALLEL_ANY = "parallel_any"


def test_parallel_cancelled_run_metrics_outcome_is_skip(
    make_provider_config,
    golden_task,
    make_run_metrics,
    make_parallel_executor,
    parallel_any_value,
) -> None:
    providers = [
        make_provider_config("winner"),
        make_provider_config("cancelled"),
    ]

    def run_single(config, _provider, _task, _attempt, mode):
        assert mode == parallel_any_value
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

    batch, stop_reason = executor.run(
        provider_pairs,
        golden_task,
        attempt_index=0,
        config=config,
    )

    assert stop_reason == "completed"
    results = {index: result for index, result in batch}

    cancelled_result = results[1]
    assert cancelled_result.metrics.status == "skip"
    assert cancelled_result.metrics.outcome == "skip"
