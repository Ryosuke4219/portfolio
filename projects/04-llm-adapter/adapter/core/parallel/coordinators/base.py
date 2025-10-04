"""Common helpers and base class for parallel coordinators."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from threading import Event
from typing import cast, TYPE_CHECKING

from ...config import ProviderConfig
from ...datasets import GoldenTask
from ...parallel_state import build_cancelled_result
from ...providers import BaseProvider

# --- モード正規化ヘルパ ---

_PARALLEL_ANY_SNAKE = "parallel_any"
_PARALLEL_ANY_LEGACY = "parallel-any"


if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from ...runner_api import RunnerConfig
    from ...runner_execution import SingleRunResult
    from ...runner_execution_parallel import ParallelAttemptExecutor

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


# --- 共通基底クラス ---


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


__all__ = [
    "_normalize_mode_value",
    "_is_parallel_any_mode",
    "_ParallelCoordinatorBase",
    "build_cancelled_result",
]
