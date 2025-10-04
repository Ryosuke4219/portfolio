"""ParallelAll coordinator implementation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from typing import TYPE_CHECKING

from ...config import ProviderConfig
from ...datasets import GoldenTask
from ...providers import BaseProvider
from .base import _ParallelCoordinatorBase

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from ...runner_api import RunnerConfig
    from ...runner_execution import SingleRunResult
    from ...runner_execution_parallel import ParallelAttemptExecutor
    from .base import _BuildCancelledResult

# --- ParallelAll 固有ロジック ---


class _ParallelAllCoordinator(_ParallelCoordinatorBase):
    def __init__(
        self,
        executor: ParallelAttemptExecutor,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
        *,
        cancel_builder: _BuildCancelledResult,
    ) -> None:
        super().__init__(
            executor,
            providers,
            task,
            attempt_index,
            config,
            cancel_builder=cancel_builder,
        )

    def execute(self) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        workers = [
            self._build_worker(index, provider_config, provider)
            for index, (provider_config, provider) in enumerate(self._providers)
        ]
        self._executor._run_parallel_all_sync(
            workers, max_concurrency=self._max_workers
        )
        return self._build_batch(), self._stop_reason

    def _build_worker(
        self, index: int, provider_config: ProviderConfig, provider: BaseProvider
    ) -> Callable[[], int]:
        def worker() -> int:
            if self._cancel_event.is_set():
                raise CancelledError()
            try:
                result = self._executor._run_single(
                    provider_config,
                    provider,
                    self._task,
                    self._attempt_index,
                    self._mode_value,
                )
                self._results[index] = result
                self._update_stop_reason(result)
                return index
            except CancelledError:
                self._mark_cancelled(index)
                raise

        return worker


__all__ = ["_ParallelAllCoordinator"]
