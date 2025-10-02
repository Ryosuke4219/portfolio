from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path

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
from adapter.core.runner_execution import SingleRunResult
from adapter.core.runner_execution_parallel import (
    ParallelAttemptExecutor,
    ProviderFailureSummary,
)

try:  # pragma: no cover - 型補完と後方互換用
    from adapter.core.runner_api import RunnerMode
except ImportError:  # pragma: no cover - RunnerMode 未導入環境向け
    class RunnerMode(str, Enum):  # type: ignore[misc]
        PARALLEL_ANY = "parallel_any"


PARALLEL_ANY_VALUE = RunnerMode.PARALLEL_ANY.value.replace("-", "_")


class FakeParallelExecutionError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.failures: Sequence[ProviderFailureSummary] | None = None
        self.batch: Sequence[tuple[int, SingleRunResult]] | None = None


def _normalize_concurrency(total: int, limit: int | None) -> int:
    if limit is None or limit <= 0:
        return total
    return max(1, min(limit, total))


@pytest.fixture
def parallel_any_value() -> str:
    return PARALLEL_ANY_VALUE


@pytest.fixture
def make_provider_config(tmp_path: Path) -> Callable[[str], ProviderConfig]:
    def _factory(name: str) -> ProviderConfig:
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

    return _factory


@pytest.fixture
def golden_task() -> GoldenTask:
    return GoldenTask(
        task_id="task",
        name="Task",
        input={},
        prompt_template="prompt",
        expected={},
    )


@pytest.fixture
def make_run_metrics(parallel_any_value: str) -> Callable[[ProviderConfig, str, str | None, str | None], RunMetrics]:
    def _factory(
        provider: ProviderConfig,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> RunMetrics:
        return RunMetrics(
            ts="2024-01-01T00:00:00Z",
            run_id=f"run-{provider.provider}",
            provider=provider.provider,
            model=provider.model,
            mode=parallel_any_value,
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

    return _factory


@pytest.fixture
def make_parallel_executor() -> Callable[[Callable[..., SingleRunResult]], ParallelAttemptExecutor]:
    def _factory(run_single: Callable[..., SingleRunResult]) -> ParallelAttemptExecutor:
        def run_parallel_all_sync(
            workers: Sequence[Callable[[], int]],
            *,
            max_concurrency: int | None = None,
        ) -> list[int]:
            return [worker() for worker in workers]

        def run_parallel_any_sync(
            workers: Sequence[Callable[[], int]],
            *,
            max_concurrency: int | None = None,
        ) -> int:
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

    return _factory


@pytest.fixture
def parallel_execution_error() -> type[FakeParallelExecutionError]:
    return FakeParallelExecutionError
