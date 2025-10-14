from __future__ import annotations

from collections.abc import Callable
from enum import Enum

import pytest

from adapter.core.datasets import GoldenTask
from adapter.core.errors import AllFailedError as AdapterAllFailedError
from adapter.core.runner_execution import SingleRunResult
from adapter.core.runner_execution_parallel import ParallelAttemptExecutor

try:
    from src.llm_adapter.errors import AllFailedError as ShadowAllFailedError
except ImportError:  # pragma: no cover - Shadow adapter 未導入環境向け
    ShadowAllFailedError = AdapterAllFailedError  # type: ignore[assignment]
    pytest.importorskip("src.llm_adapter.errors")

try:  # pragma: no cover - 型補完と後方互換用
    from adapter.core.runner_api import RunnerConfig, RunnerMode
except ImportError:  # pragma: no cover - RunnerMode 未導入環境向け
    from adapter.core.runner_api import RunnerConfig

    class RunnerMode(str, Enum):  # type: ignore[misc]
        PARALLEL_ANY = "parallel_any"


def test_parallel_any_without_providers_raises_all_failed(
    make_parallel_executor: Callable[[Callable[..., SingleRunResult]], ParallelAttemptExecutor],
    golden_task: GoldenTask,
) -> None:
    executor = make_parallel_executor(lambda *_args, **_kwargs: pytest.fail("run_single should not be called"))
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ANY)

    assert AdapterAllFailedError is ShadowAllFailedError

    with pytest.raises(AdapterAllFailedError) as excinfo:
        executor.run([], golden_task, attempt_index=0, config=config)

    assert isinstance(excinfo.value.failures, list)
    assert excinfo.value.failures == []


__all__ = ["test_parallel_any_without_providers_raises_all_failed"]
