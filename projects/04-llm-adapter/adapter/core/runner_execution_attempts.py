"""Attempt executor helpers for :mod:`adapter.core.runner_execution`."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Protocol

from .config import ProviderConfig
from .datasets import GoldenTask
from .providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig
    from .runner_execution import SingleRunResult


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
    "SingleRunResult",
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
    ) -> tuple[list[tuple[int, "SingleRunResult"]], str | None]:
        batch: list[tuple[int, "SingleRunResult"]] = []
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
        config: "RunnerConfig",
    ) -> tuple[list[tuple[int, "SingleRunResult"]], str | None]:
        if not providers:
            return [], None

        max_concurrency = getattr(config, "max_concurrency", None)
        max_workers = self._normalize_concurrency(len(providers), max_concurrency)

        stop_reason: str | None = None
        results: list["SingleRunResult" | None] = [None] * len(providers)

        def build_worker(
            index: int, provider_config: ProviderConfig, provider: BaseProvider
        ) -> Callable[[], int]:
            def worker() -> int:
                nonlocal stop_reason
                result = self._run_single(
                    provider_config,
                    provider,
                    task,
                    attempt_index,
                    config.mode,
                )
                results[index] = result
                if result.stop_reason and not stop_reason:
                    stop_reason = result.stop_reason
                if config.mode == "parallel-any" and result.metrics.status != "ok":
                    raise RuntimeError("parallel-any failure")
                return index

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
