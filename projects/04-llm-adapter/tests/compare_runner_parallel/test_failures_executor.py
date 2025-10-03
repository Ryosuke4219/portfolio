from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import sys
from typing import TYPE_CHECKING, cast

import pytest

from adapter.core.models import ProviderConfig
from adapter.core.providers import BaseProvider
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult
from adapter.core.runner_execution_parallel import (
    ParallelAttemptExecutor,
    ProviderFailureSummary,
)
if TYPE_CHECKING:
    from tests.compare_runner_parallel.conftest import (
        ProviderConfigFactory,
        RunMetricsFactory,
        TaskFactory,
    )


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
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
    behaviours: dict[str, dict[str, dict[str, object]]] | None = None,
) -> tuple[list[tuple[int, SingleRunResult]], list[ProviderFailureSummary], str | None]:
    from adapter.core.runner_execution_parallel import ParallelAnyState

    task = task_factory()
    providers = [
        provider_config_factory(tmp_path, name=n, provider=n, model=n)
        for n in ("fail", "win", "tail")
    ]
    summaries: list[ProviderFailureSummary] = []
    if mode == "parallel_any":
        def _record(self: ParallelAnyState, index: int, summary: ProviderFailureSummary) -> None:
            summaries.append(summary)
            ParallelAnyState.register_failure(self, index, summary)

        monkeypatch.setattr(
            "adapter.core.runner_execution_parallel.ParallelAnyState",
            type("RecordingState", (ParallelAnyState,), {"register_failure": _record}),
        )
    state_factory = sys.modules["adapter.core.runner_execution_parallel"].ParallelAnyState
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
        "parallel_all": {**{name: {} for name in ("fail", "tail")}, "win": {"stop": "all-done"}},
    }

    def run_single(
        config: ProviderConfig,
        _provider: object,
        _task: object,
        _attempt: int,
        _mode: str,
    ) -> SingleRunResult:
        metrics = run_metrics_factory(
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
            error=data.get("error") if isinstance(data.get("error"), Exception) else None,
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
    except RuntimeError as exc:  # pragma: no cover - fallback path
        error_batch = getattr(exc, "batch", [])
        error_failures = getattr(exc, "failures", [])
        if not summaries and error_failures:
            summaries.extend(error_failures)
        return list(error_batch), summaries, None
    return list(batch), summaries, stop_reason


@pytest.mark.parametrize(("mode", "expected_stop"), [("parallel_any", "completed"), ("parallel_all", "all-done")])
def test_parallel_executor_parallel_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
    mode: str,
    expected_stop: str,
) -> None:
    batch, summaries, stop_reason = _run_parallel_case(
        tmp_path,
        monkeypatch,
        mode,
        provider_config_factory,
        task_factory,
        run_metrics_factory,
    )
    assert stop_reason == expected_stop
    results = dict(batch)
    if mode == "parallel_any":
        assert results[2].metrics.failure_kind == "cancelled"
        assert summaries[0].backoff_next_provider is True
        assert summaries[0].error_type == "RuntimeError"
    else:
        assert results[1].stop_reason == expected_stop


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
