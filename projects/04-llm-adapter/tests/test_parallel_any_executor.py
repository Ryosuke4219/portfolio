from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest

from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot, EvalMetrics, RunMetrics
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import BaseProvider
from adapter.core.runner_execution import SingleRunResult
from adapter.core.runner_execution_parallel import (
    _ParallelCoordinatorBase,
    ParallelAttemptExecutor,
    ProviderFailureSummary,
)

try:  # pragma: no cover - 型補完と後方互換用
    from adapter.core.runner_api import RunnerConfig, RunnerMode
except ImportError:  # pragma: no cover - RunnerMode 未導入環境向け
    from enum import Enum

    from adapter.core.runner_api import RunnerConfig

    class RunnerMode(str, Enum):
        SEQUENTIAL = "sequential"
        PARALLEL_ANY = "parallel_any"
        PARALLEL_ALL = "parallel-all"
        CONSENSUS = "consensus"


PARALLEL_ANY_VALUE = RunnerMode.PARALLEL_ANY.value.replace("-", "_")


from src.llm_adapter.errors import AllFailedError
from src.llm_adapter.parallel_exec import run_parallel_all_sync, run_parallel_any_sync
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerConfig as SyncRunnerConfig
from src.llm_adapter.runner_config import RunnerMode as SyncRunnerMode
from src.llm_adapter.runner_sync import Runner as SyncRunner
from src.llm_adapter.runner_sync_modes import get_sync_strategy, SyncRunContext
from src.llm_adapter.runner_sync_parallel_any import ParallelAnyStrategy
from src.llm_adapter.utils import content_hash


class FakeParallelExecutionError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.failures: Sequence[ProviderFailureSummary] | None = None
        self.batch: Sequence[tuple[int, SingleRunResult]] | None = None


def _make_provider_config(tmp_path: Path, name: str) -> ProviderConfig:
    return ProviderConfig(
        path=tmp_path / f"{name}.yaml",
        schema_version=1,
        provider=name,
        endpoint=None,
        model=f"model-{name}",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=1,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def _make_task() -> GoldenTask:
    return GoldenTask(
        task_id="task",
        name="Task",
        input={},
        prompt_template="prompt",
        expected={},
    )


def _normalize_concurrency(total: int, limit: int | None) -> int:
    if limit is None or limit <= 0:
        return total
    return max(1, min(limit, total))


def _make_executor(run_single: Callable[..., SingleRunResult]) -> ParallelAttemptExecutor:
    def run_parallel_all_sync(workers: Sequence[Callable[[], int]], *, max_concurrency: int | None = None) -> list[int]:
        return [worker() for worker in workers]

    def run_parallel_any_sync(workers: Sequence[Callable[[], int]], *, max_concurrency: int | None = None) -> int:
        errors: list[BaseException] = []
        for worker in workers:
            try:
                return worker()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                continue
        raise FakeParallelExecutionError("parallel_any failed") from (
            errors[-1] if errors else None
        )

    return ParallelAttemptExecutor(
        run_single,
        _normalize_concurrency,
        run_parallel_all_sync=run_parallel_all_sync,
        run_parallel_any_sync=run_parallel_any_sync,
        parallel_execution_error=FakeParallelExecutionError,
    )


def _make_metrics(
    provider: ProviderConfig,
    *,
    status: str,
    failure_kind: str | None,
    error_message: str | None,
) -> RunMetrics:
    return RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id=f"run-{provider.provider}",
        provider=provider.provider,
        model=provider.model,
        mode=PARALLEL_ANY_VALUE,
        prompt_id="prompt",
        prompt_name="prompt",
        seed=provider.seed,
        temperature=provider.temperature,
        top_p=provider.top_p,
        max_tokens=provider.max_tokens,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        cost_usd=0.0,
        status=status,
        failure_kind=failure_kind,
        error_message=error_message,
        output_text=None,
        output_hash=None,
        eval=EvalMetrics(),
        budget=BudgetSnapshot(0.0, False),
        ci_meta={},
    )


def test_parallel_any_success_marks_failures_and_cancellations(tmp_path: Path) -> None:
    task = _make_task()
    providers = [
        _make_provider_config(tmp_path, "failure"),
        _make_provider_config(tmp_path, "winner"),
        _make_provider_config(tmp_path, "cancelled"),
    ]
    failure_error = RuntimeError("boom")

    def run_single(
        config: ProviderConfig,
        _provider: object,
        _task: GoldenTask,
        _attempt: int,
        _mode: str,
    ) -> SingleRunResult:
        assert _mode == PARALLEL_ANY_VALUE
        if config.provider == "failure":
            metrics = _make_metrics(
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
        metrics = _make_metrics(
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

    executor = _make_executor(run_single)
    provider_pairs = [(cfg, cast(BaseProvider, object())) for cfg in providers]
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ANY)

    batch, stop_reason = executor.run(provider_pairs, task, attempt_index=0, config=config)

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


def test_parallel_any_all_failures_raise_parallel_error(tmp_path: Path) -> None:
    task = _make_task()
    providers = [
        _make_provider_config(tmp_path, "first"),
        _make_provider_config(tmp_path, "second"),
    ]

    def run_single(
        config: ProviderConfig,
        _provider: object,
        _task: GoldenTask,
        _attempt: int,
        _mode: str,
    ) -> SingleRunResult:
        assert _mode == PARALLEL_ANY_VALUE
        metrics = _make_metrics(
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

    executor = _make_executor(run_single)
    provider_pairs = [(cfg, cast(BaseProvider, object())) for cfg in providers]
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ANY)

    with pytest.raises(FakeParallelExecutionError) as excinfo:
        executor.run(provider_pairs, task, attempt_index=0, config=config)

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


def test_parallel_any_mode_accepts_hyphen_compatibility(tmp_path: Path) -> None:
    task = _make_task()
    providers = [_make_provider_config(tmp_path, "winner")]

    observed_modes: list[str] = []

    def run_single(
        config: ProviderConfig,
        _provider: object,
        _task: GoldenTask,
        _attempt: int,
        _mode: str,
    ) -> SingleRunResult:
        observed_modes.append(_mode)
        metrics = _make_metrics(
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

    executor = _make_executor(run_single)
    provider_pairs = [(cfg, cast(BaseProvider, object())) for cfg in providers]
    config = RunnerConfig(mode="parallel-any")

    batch, stop_reason = executor.run(
        provider_pairs, task, attempt_index=0, config=config
    )

    assert observed_modes == [PARALLEL_ANY_VALUE]
    assert stop_reason == "completed"
    assert len(batch) == 1
    index, result = batch[0]
    assert index == 0
    assert result.raw_output == "ok"


def test_get_sync_strategy_parallel_any_propagates_all_failed(tmp_path: Path) -> None:
    class _StubProvider(ProviderSPI):
        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - not invoked
            raise AssertionError("provider should not be invoked")

    provider = _StubProvider("stub")
    metrics_path = tmp_path / "metrics.jsonl"
    config = SyncRunnerConfig(
        mode=SyncRunnerMode.PARALLEL_ANY,
        max_attempts=0,
        metrics_path=str(metrics_path),
    )
    runner = SyncRunner([provider], config=config)
    request = ProviderRequest(model="test", prompt="hello")
    request_fingerprint = content_hash(
        "runner",
        request.prompt_text,
        request.options,
        request.max_tokens,
    )
    metadata = {
        "run_id": request_fingerprint,
        "mode": config.mode.value,
        "providers": [provider.name()],
        "shadow_used": False,
        "shadow_provider_id": None,
    }
    context = SyncRunContext(
        runner=runner,
        request=request,
        event_logger=None,
        metadata=metadata,
        run_started=0.0,
        request_fingerprint=request_fingerprint,
        shadow=None,
        shadow_used=False,
        metrics_path=str(metrics_path),
        run_parallel_all=run_parallel_all_sync,
        run_parallel_any=run_parallel_any_sync,
    )

    strategy = get_sync_strategy(config.mode)
    assert isinstance(strategy, ParallelAnyStrategy)

    with pytest.raises(AllFailedError):
        strategy.execute(context)
