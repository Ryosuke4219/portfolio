"""ParallelAny coordinator implementation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from threading import Event
from typing import TYPE_CHECKING

from ...config import ProviderConfig
from ...datasets import GoldenTask
from ...parallel_state import ParallelAnyState, ProviderFailureSummary
from ...providers import BaseProvider
from .base import _ParallelCoordinatorBase

# --- ParallelAny 固有ロジック ---


if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from ...runner_api import RunnerConfig
    from ...runner_execution import SingleRunResult
    from ...runner_execution_parallel import ParallelAttemptExecutor
    from .base import _BuildCancelledResult

_StateFactory = Callable[[Event], ParallelAnyState]


class _ParallelAnyCoordinator(_ParallelCoordinatorBase):
    def __init__(
        self,
        executor: ParallelAttemptExecutor,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
        *,
        cancel_builder: _BuildCancelledResult,
        state_factory: _StateFactory,
    ) -> None:
        super().__init__(
            executor,
            providers,
            task,
            attempt_index,
            config,
            cancel_builder=cancel_builder,
        )
        self._state = state_factory(self._cancel_event)

    def execute(self) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        workers = [
            self._build_worker(index, provider_config, provider)
            for index, (provider_config, provider) in enumerate(self._providers)
        ]
        parallel_error = self._executor._parallel_execution_error
        try:
            self._executor._run_parallel_any_sync(
                workers, max_concurrency=self._max_workers
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, parallel_error) or isinstance(exc, RuntimeError):
                self._state.record_caught_error(exc)
            else:
                raise
        self._finalize()
        return self._build_batch(), self._stop_reason

    def _build_worker(
        self, index: int, provider_config: ProviderConfig, provider: BaseProvider
    ) -> Callable[[], int]:
        def worker() -> int:
            if self._state.should_cancel():
                raise CancelledError()
            try:
                result = self._executor._run_single(
                    provider_config,
                    provider,
                    self._task,
                    self._attempt_index,
                    self._mode_value,
                )
                should_cancel = self._state.should_cancel()
                metrics = result.metrics
                if metrics.status != "ok":
                    if metrics.status == "error":
                        metrics.outcome = "error"
                    self._results[index] = result
                    summary = self._build_failure_summary(
                        index, provider_config, result
                    )
                    self._state.register_failure(index, summary)
                    raise RuntimeError("parallel_any failure")
                should_cancel = self._state.register_success(index) or should_cancel
                self._results[index] = result
                if should_cancel:
                    raise CancelledError()
                self._update_stop_reason(result)
                return index
            except CancelledError:
                self._mark_cancelled(index)
                raise

        return worker

    def _finalize(self) -> None:
        for index, result in enumerate(self._results):
            if result is None:
                self._mark_cancelled(index)
        self._state.finalize(
            self._providers,
            self._results,
            self._build_failure_summary,
            self._executor._parallel_execution_error,
        )

    def _build_failure_summary(
        self,
        index: int,
        provider_config: ProviderConfig,
        result: SingleRunResult,
    ) -> ProviderFailureSummary:
        metrics = result.metrics
        return ProviderFailureSummary(
            index=index,
            provider=provider_config.provider,
            status=metrics.status,
            failure_kind=metrics.failure_kind,
            error_message=metrics.error_message,
            backoff_next_provider=result.backoff_next_provider,
            retries=metrics.retries,
            error_type=type(result.error).__name__ if result.error else None,
        )


__all__ = ["_ParallelAnyCoordinator"]
