"""Parallel attempt executor helpers for :mod:`adapter.core.runner_execution`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Event
from typing import Protocol, TYPE_CHECKING

from .config import ProviderConfig
from .datasets import GoldenTask
from .errors import AllFailedError
from .parallel.coordinators import (
    _is_parallel_any_mode,
    _normalize_mode_value,
    _ParallelAllCoordinator,
    _ParallelAnyCoordinator,
    _ParallelCoordinatorBase,
    build_cancelled_result,
    ProviderFailureSummary,
)
from .parallel_state import ParallelAnyState
from .providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig
    from .runner_execution import SingleRunResult

    _RunSingle = Callable[
        [ProviderConfig, BaseProvider, GoldenTask, int, str],
        SingleRunResult,
    ]
else:
    _RunSingle = Callable[[ProviderConfig, BaseProvider, GoldenTask, int, str], object]

if TYPE_CHECKING:
    _BuildCancelledResult = Callable[
        [ProviderConfig, GoldenTask, int, RunnerConfig, str],
        SingleRunResult,
    ]
else:
    _BuildCancelledResult = Callable[
        [ProviderConfig, GoldenTask, int, object, str],
        object,
    ]
_StateFactory = Callable[[Event], ParallelAnyState]


class _ParallelRunner(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], int]],
        *,
        max_concurrency: int | None = None,
    ) -> object: ...


class ParallelAttemptExecutor:
    """Executor to handle parallel provider attempts."""

    def __init__(
        self,
        run_single: _RunSingle,
        normalize_concurrency: Callable[[int, int | None], int],
        *,
        run_parallel_all_sync: _ParallelRunner,
        run_parallel_any_sync: _ParallelRunner,
        parallel_execution_error: type[Exception],
        build_cancelled_result: _BuildCancelledResult = build_cancelled_result,
        parallel_any_state_factory: _StateFactory = ParallelAnyState,
    ) -> None:
        self._run_single = run_single
        self._normalize_concurrency = normalize_concurrency
        self._run_parallel_all_sync = run_parallel_all_sync
        self._run_parallel_any_sync = run_parallel_any_sync
        self._parallel_execution_error = parallel_execution_error
        self._build_cancelled_result = build_cancelled_result
        self._parallel_any_state_factory = parallel_any_state_factory

    def run(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        if not providers:
            error = AllFailedError("no providers were attempted")
            setattr(error, "failures", [])
            setattr(error, "batch", [])
            setattr(error, "stop_reason", None)
            raise error
        normalized_mode = _normalize_mode_value(config.mode)
        if _is_parallel_any_mode(normalized_mode):
            coordinator: _ParallelCoordinatorBase = _ParallelAnyCoordinator(
                self,
                providers,
                task,
                attempt_index,
                config,
                cancel_builder=self._build_cancelled_result,
                state_factory=self._parallel_any_state_factory,
            )
        else:
            coordinator = _ParallelAllCoordinator(
                self,
                providers,
                task,
                attempt_index,
                config,
                cancel_builder=self._build_cancelled_result,
            )
        return coordinator.execute()


__all__ = [
    "ParallelAttemptExecutor",
    "ProviderFailureSummary",
]
