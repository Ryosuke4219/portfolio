"""Attempt executor helpers for :mod:`adapter.core.runner_execution`."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from threading import Event, Lock
from typing import Any, Protocol, TYPE_CHECKING

from .runner_execution import SingleRunResult

from .config import ProviderConfig
from .datasets import GoldenTask
from .providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig
    from .runner_execution import SingleRunResult
else:  # pragma: no cover - 実行時循環参照対策
    SingleRunResult = Any  # type: ignore[assignment]


class _ParallelRunner(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], int]],
        *,
        max_concurrency: int | None = None,
    ) -> object:
        ...


_RunSingle = Callable[
    [ProviderConfig, BaseProvider, GoldenTask, int, str],
    SingleRunResult,
]


class SequentialAttemptExecutor:
    """Executor to handle sequential provider attempts."""

    def __init__(self, run_single: _RunSingle) -> None:
        self._run_single = run_single

    def run(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> tuple[list[tuple[int, SingleRunResult]], str | None]:
        batch: list[tuple[int, SingleRunResult]] = []
        stop_reason: str | None = None
        for index, (provider_config, provider) in enumerate(providers):
            result = self._run_single(provider_config, provider, task, attempt_index, mode)
            batch.append((index, result))
            if result.stop_reason and not stop_reason:
                stop_reason = result.stop_reason
        return batch, stop_reason


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

        max_concurrency = getattr(config, "max_concurrency", None)
        max_workers = self._normalize_concurrency(len(providers), max_concurrency)

        stop_reason: str | None = None
        results: list[SingleRunResult | None] = [None] * len(providers)
        cancel_event = Event()
        winner_lock = Lock()
        winner_index: int | None = None

        cancel_message = "parallel-any cancelled after winner"

        def mark_cancelled(index: int) -> None:
            result = results[index]
            if result is not None:
                metrics = result.metrics
                metrics.status = "skip"
                if not metrics.failure_kind:
                    metrics.failure_kind = "cancelled"
                metrics.error_message = cancel_message
                result.stop_reason = result.stop_reason or "cancelled"
                return
            provider_config, _ = providers[index]
            from .metrics import BudgetSnapshot, EvalMetrics, RunMetrics, now_ts
            from .runner_execution import SingleRunResult as _SingleRunResult
            import uuid

            metrics = RunMetrics(
                ts=now_ts(),
                run_id=f"run_{task.task_id}_{attempt_index}_{uuid.uuid4().hex}",
                provider=provider_config.provider,
                model=provider_config.model,
                mode=config.mode,
                prompt_id=task.task_id,
                prompt_name=task.name,
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
                error_message=cancel_message,
                output_text=None,
                output_hash=None,
                eval=EvalMetrics(),
                budget=BudgetSnapshot(0.0, False),
                ci_meta={},
            )
            results[index] = _SingleRunResult(
                metrics=metrics,
                raw_output="",
                stop_reason="cancelled",
            )

        def build_worker(
            index: int, provider_config: ProviderConfig, provider: BaseProvider
        ) -> Callable[[], int]:
            def worker() -> int:
                nonlocal stop_reason, winner_index
                if cancel_event.is_set():
                    raise CancelledError()
                try:
                    result = self._run_single(
                        provider_config,
                        provider,
                        task,
                        attempt_index,
                        config.mode,
                    )
                    should_cancel = cancel_event.is_set()
                    if config.mode == "parallel-any":
                        if result.metrics.status != "ok":
                            results[index] = result
                            raise RuntimeError("parallel-any failure")
                        with winner_lock:
                            if winner_index is None:
                                winner_index = index
                                cancel_event.set()
                                should_cancel = False
                            else:
                                should_cancel = winner_index != index
                    results[index] = result
                    if should_cancel:
                        raise CancelledError()
                    if result.stop_reason and not stop_reason:
                        stop_reason = result.stop_reason
                    return index
                except CancelledError:
                    mark_cancelled(index)
                    raise

            return worker

        workers = [
            build_worker(index, provider_config, provider)
            for index, (provider_config, provider) in enumerate(providers)
        ]
        if config.mode == "parallel-any":
            try:
                self._run_parallel_any_sync(workers, max_concurrency=max_workers)
            except (self._parallel_execution_error, RuntimeError):
                pass
        else:
            self._run_parallel_all_sync(workers, max_concurrency=max_workers)

        if config.mode == "parallel-any":
            for index, result in enumerate(results):
                if result is None:
                    mark_cancelled(index)

        batch = [
            (index, result)
            for index, result in enumerate(results)
            if result is not None
        ]
        return batch, stop_reason


__all__ = [
    "SequentialAttemptExecutor",
    "ParallelAttemptExecutor",
]
