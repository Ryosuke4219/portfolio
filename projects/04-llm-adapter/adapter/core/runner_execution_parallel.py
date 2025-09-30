"""Parallel attempt executor helpers for :mod:`adapter.core.runner_execution`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any, Protocol, TYPE_CHECKING
import uuid

from .config import ProviderConfig
from .datasets import GoldenTask
from .metrics import BudgetSnapshot, EvalMetrics, now_ts, RunMetrics
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


class _ParallelRunner(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], int]],
        *,
        max_concurrency: int | None = None,
    ) -> object:
        ...


_single_run_result_cls: type[Any] | None = None


def _get_single_run_result_cls() -> type[SingleRunResult]:
    global _single_run_result_cls
    if _single_run_result_cls is None:
        from .runner_execution import SingleRunResult as _SingleRunResult

        _single_run_result_cls = _SingleRunResult
    return _single_run_result_cls


@dataclass(frozen=True, slots=True)
class ProviderFailureSummary:
    index: int
    provider: str
    status: str
    failure_kind: str | None
    error_message: str | None
    backoff_next_provider: bool
    retries: int
    error_type: str | None


class _ParallelCoordinatorBase:
    CANCEL_MESSAGE = "parallel-any cancelled after winner"

    def __init__(
        self,
        executor: ParallelAttemptExecutor,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
    ) -> None:
        self._executor = executor
        self._providers = providers
        self._task = task
        self._attempt_index = attempt_index
        self._config = config
        max_concurrency = getattr(config, "max_concurrency", None)
        self._max_workers = executor._normalize_concurrency(
            len(providers), max_concurrency
        )
        self._results: list[SingleRunResult | None] = [None] * len(providers)
        self._stop_reason: str | None = None
        self._cancel_event = Event()

    def execute(self) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        raise NotImplementedError

    def _mark_cancelled(self, index: int) -> None:
        result = self._results[index]
        if result is not None:
            metrics = result.metrics
            metrics.status = "skip"
            if not metrics.failure_kind:
                metrics.failure_kind = "cancelled"
            metrics.error_message = self.CANCEL_MESSAGE
            result.stop_reason = result.stop_reason or "cancelled"
            return
        provider_config, _ = self._providers[index]
        metrics = RunMetrics(
            ts=now_ts(),
            run_id=f"run_{self._task.task_id}_{self._attempt_index}_{uuid.uuid4().hex}",
            provider=provider_config.provider,
            model=provider_config.model,
            mode=self._config.mode,
            prompt_id=self._task.task_id,
            prompt_name=self._task.name,
            seed=provider_config.seed,
            temperature=provider_config.temperature,
            top_p=provider_config.top_p,
            max_tokens=provider_config.max_tokens,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            cost_usd=0.0,
            status="skip",
            failure_kind="cancelled",
            error_message=self.CANCEL_MESSAGE,
            output_text=None,
            output_hash=None,
            eval=EvalMetrics(),
            budget=BudgetSnapshot(0.0, False),
            ci_meta={},
        )
        single_run_result_cls = _get_single_run_result_cls()
        self._results[index] = single_run_result_cls(
            metrics=metrics,
            raw_output="",
            stop_reason="cancelled",
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
                    self._config.mode,
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
    ) -> None:
        super().__init__(executor, providers, task, attempt_index, config)
        self._failure_lock = Lock()
        self._winner_lock = Lock()
        self._failure_indices: set[int] = set()
        self._failure_summaries: list[ProviderFailureSummary] = []
        self._winner_index: int | None = None
        self._caught_error: Exception | None = None

    def execute(self) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        workers = [
            self._build_worker(index, provider_config, provider)
            for index, (provider_config, provider) in enumerate(self._providers)
        ]
        try:
            self._executor._run_parallel_any_sync(
                workers, max_concurrency=self._max_workers
            )
        except self._executor._parallel_execution_error as exc:  # type: ignore[misc]
            self._caught_error = exc
        except RuntimeError as exc:
            self._caught_error = exc
        self._finalize()
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
                    self._config.mode,
                )
                should_cancel = self._cancel_event.is_set()
                if result.metrics.status != "ok":
                    self._results[index] = result
                    summary = self._build_failure_summary(index, provider_config, result)
                    with self._failure_lock:
                        self._failure_summaries.append(summary)
                        self._failure_indices.add(index)
                    raise RuntimeError("parallel-any failure")
                with self._winner_lock:
                    if self._winner_index is None:
                        self._winner_index = index
                        self._cancel_event.set()
                        should_cancel = False
                    else:
                        should_cancel = self._winner_index != index
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
        success_found = any(
            result is not None and result.metrics.status == "ok"
            for result in self._results
        )
        if success_found:
            return
        for index, result in enumerate(self._results):
            if result is None or index in self._failure_indices:
                continue
            provider_config, _ = self._providers[index]
            summary = self._build_failure_summary(index, provider_config, result)
            self._failure_summaries.append(summary)
            self._failure_indices.add(index)
        error = self._executor._parallel_execution_error("parallel-any failed")
        error.failures = self._failure_summaries  # type: ignore[attr-defined]
        error.batch = [
            (index, result)
            for index, result in enumerate(self._results)
            if result is not None
        ]  # type: ignore[attr-defined]
        if self._caught_error is not None:
            raise error from self._caught_error
        raise error

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
    ) -> None:
        self._run_single = run_single
        self._normalize_concurrency = normalize_concurrency
        self._run_parallel_all_sync = run_parallel_all_sync
        self._run_parallel_any_sync = run_parallel_any_sync
        self._parallel_execution_error = parallel_execution_error

    def run(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        config: RunnerConfig,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        if not providers:
            return [], None
        if config.mode == "parallel-any":
            coordinator: _ParallelCoordinatorBase = _ParallelAnyCoordinator(
                self, providers, task, attempt_index, config
            )
        else:
            coordinator = _ParallelAllCoordinator(
                self, providers, task, attempt_index, config
            )
        return coordinator.execute()


__all__ = [
    "ParallelAttemptExecutor",
    "ProviderFailureSummary",
]

