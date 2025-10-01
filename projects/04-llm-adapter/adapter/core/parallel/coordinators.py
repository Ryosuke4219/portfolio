"""Parallel coordinator implementations for :mod:`adapter.core.runner_execution_parallel`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from enum import Enum
from threading import Event
from typing import cast, TYPE_CHECKING

from ..config import ProviderConfig
from ..datasets import GoldenTask
from ..parallel_state import (
    build_cancelled_result,
    ParallelAnyState,
    ProviderFailureSummary,
)

_PARALLEL_ANY_SNAKE = "parallel_any"
_PARALLEL_ANY_LEGACY = "parallel-any"
from ..providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from ..runner_api import RunnerConfig
    from ..runner_execution import SingleRunResult
    from ..runner_execution_parallel import ParallelAttemptExecutor

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

if TYPE_CHECKING:
    _StateFactory = Callable[[Event], ParallelAnyState]
else:
    _StateFactory = Callable[[Event], ParallelAnyState]


def _normalize_mode_value(mode: object) -> str:
    if isinstance(mode, Enum):
        value = cast(str, mode.value)
    else:
        value = cast(str, mode)
    if value == _PARALLEL_ANY_LEGACY:
        return _PARALLEL_ANY_SNAKE
    if value == _PARALLEL_ANY_SNAKE:
        return _PARALLEL_ANY_SNAKE
    return value


def _is_parallel_any_mode(mode: object) -> bool:
    normalized = _normalize_mode_value(mode)
    return normalized in {_PARALLEL_ANY_SNAKE, _PARALLEL_ANY_LEGACY}


class _ParallelCoordinatorBase:
    CANCEL_MESSAGE = "parallel_any cancelled after winner"
    LEGACY_CANCEL_MESSAGE = "parallel-any cancelled after winner"

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
        self._executor = executor
        self._providers = providers
        self._task = task
        self._attempt_index = attempt_index
        self._config = config
        self._build_cancelled_result = cancel_builder
        max_concurrency = getattr(config, "max_concurrency", None)
        self._max_workers = executor._normalize_concurrency(
            len(providers), max_concurrency
        )
        self._results: list[SingleRunResult | None] = [None] * len(providers)
        self._stop_reason: str | None = None
        self._cancel_event = Event()
        self._mode_value = _normalize_mode_value(config.mode)

    def execute(self) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        raise NotImplementedError

    def _mark_cancelled(self, index: int) -> None:
        result = self._results[index]
        if result is not None:
            metrics = result.metrics
            metrics.status = "skip"
            if not metrics.failure_kind:
                metrics.failure_kind = "cancelled"
            if metrics.error_message == self.LEGACY_CANCEL_MESSAGE:
                metrics.error_message = self.CANCEL_MESSAGE
            elif metrics.error_message != self.CANCEL_MESSAGE:
                metrics.error_message = self.CANCEL_MESSAGE
            result.stop_reason = result.stop_reason or "cancelled"
            return
        provider_config, _ = self._providers[index]
        self._results[index] = self._build_cancelled_result(
            provider_config,
            self._task,
            self._attempt_index,
            self._config,
            self.CANCEL_MESSAGE,
        )

    def _update_stop_reason(self, result: SingleRunResult) -> None:
        if result.stop_reason and not self._stop_reason:
            self._stop_reason = result.stop_reason

    def _build_batch(self) -> list[tuple[int, SingleRunResult]]:
        return [
            (index, result)
            for index, result in enumerate(self._results)
            if result is not None
        ]


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
                if result.metrics.status != "ok":
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


__all__ = [
    "_ParallelCoordinatorBase",
    "_ParallelAllCoordinator",
    "_ParallelAnyCoordinator",
    "_normalize_mode_value",
    "_is_parallel_any_mode",
    "ProviderFailureSummary",
    "build_cancelled_result",
]
