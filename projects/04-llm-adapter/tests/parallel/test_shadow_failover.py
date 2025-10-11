from __future__ import annotations

from collections.abc import Callable
from enum import Enum

import pytest

pytest.importorskip("src.llm_adapter.errors")

from adapter.core.errors import AllFailedError
from adapter.core.runner_execution_parallel import ParallelAttemptExecutor
from adapter.core.runner_execution import SingleRunResult
from adapter.core.datasets import GoldenTask
from src.llm_adapter.errors import AllFailedError
from src.llm_adapter.parallel_exec import run_parallel_all_sync, run_parallel_any_sync
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerConfig as SyncRunnerConfig, RunnerMode as SyncRunnerMode
from src.llm_adapter.runner_sync import Runner as SyncRunner
from src.llm_adapter.runner_sync_modes import get_sync_strategy, SyncRunContext
from src.llm_adapter.runner_sync_parallel_any import ParallelAnyStrategy
from src.llm_adapter.utils import content_hash

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

    with pytest.raises(AllFailedError) as excinfo:
        executor.run([], golden_task, attempt_index=0, config=config)

    assert isinstance(excinfo.value.failures, list)
    assert excinfo.value.failures == []


__all__ = ["test_parallel_any_without_providers_raises_all_failed"]
