"""Parallel execution helpers shared across runner implementations."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import (
    as_completed,
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from . import parallel_async as _parallel_async
from .errors import ParallelExecutionError

T = TypeVar("T")
S = TypeVar("S")


SyncWorker = Callable[[], T]
@dataclass(slots=True)
class ParallelAllResult(Generic[T, S]):
    """Container capturing every result from ``run_parallel_all_*`` helpers."""

    items: Sequence[T]
    _extract: Callable[[T], S]

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("ParallelAllResult requires at least one item")

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> T:
        return self.items[index]

    @property
    def invocations(self) -> Sequence[T]:
        return self.items

    @property
    def responses(self) -> list[S]:
        return [self._extract(item) for item in self.items]

    @property
    def primary_invocation(self) -> T:
        return self.items[0]

    @property
    def primary_response(self) -> S:
        return self._extract(self.primary_invocation)

    def __getattr__(self, name: str) -> Any:
        primary = self.primary_response
        if hasattr(primary, name):
            return getattr(primary, name)
        msg = f"{type(self).__name__} has no attribute {name!r}"
        raise AttributeError(msg)


def _normalize_concurrency(total: int, limit: int | None) -> int:
    if limit is None or limit <= 0:
        return max(total, 1)
    return max(min(limit, total), 1)


def run_parallel_any_sync(
    workers: Sequence[SyncWorker[T]],
    *,
    max_concurrency: int | None = None,
    on_cancelled: Callable[[Sequence[int]], None] | None = None,
) -> T:
    """Execute workers concurrently until the first success."""

    if not workers:
        raise ValueError("workers must not be empty")
    total_workers = len(workers)
    max_workers = _normalize_concurrency(total_workers, max_concurrency)
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map: dict[Future[T], int] = {}
        next_index = 0

        def _submit_next() -> None:
            nonlocal next_index
            if next_index >= total_workers:
                return
            idx = next_index
            next_index += 1
            future_map[executor.submit(workers[idx])] = idx

        for _ in range(min(max_workers, total_workers)):
            _submit_next()

        while future_map:
            done, _ = wait(future_map, return_when=FIRST_COMPLETED)
            for future in done:
                index = future_map.pop(future, None)
                if index is None:
                    continue
                try:
                    result = future.result()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    _submit_next()
                    continue
                cancelled: tuple[int, ...] = ()
                if on_cancelled is not None:
                    pending_indices = list(future_map.values())
                    if next_index < total_workers:
                        pending_indices.extend(range(next_index, total_workers))
                    if pending_indices:
                        cancelled = tuple(sorted(pending_indices))
                for pending_future in list(future_map):
                    pending_future.cancel()
                if on_cancelled is not None and cancelled:
                    on_cancelled(cancelled)
                return result
    raise ParallelExecutionError("all workers failed") from errors[-1] if errors else None


def run_parallel_all_sync(
    workers: Sequence[SyncWorker[T]], *, max_concurrency: int | None = None
) -> list[T]:
    """Execute workers concurrently and return all successful results."""

    if not workers:
        raise ValueError("workers must not be empty")
    max_workers = _normalize_concurrency(len(workers), max_concurrency)
    responses: list[T] = [None] * len(workers)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(worker): idx for idx, worker in enumerate(workers)}
        try:
            for future in as_completed(future_map):
                responses[future_map[future]] = future.result()
        except BaseException:
            for pending in future_map:
                pending.cancel()
            raise
    return responses

AsyncWorker = _parallel_async.AsyncWorker
RetryDirective = _parallel_async.RetryDirective
_AsyncParallelExecutor = _parallel_async._AsyncParallelExecutor
run_parallel_all_async = _parallel_async.run_parallel_all_async
run_parallel_any_async = _parallel_async.run_parallel_any_async
asyncio = _parallel_async.asyncio


__all__ = [
    "AsyncWorker",
    "_AsyncParallelExecutor",
    "ParallelAllResult",
    "ParallelExecutionError",
    "RetryDirective",
    "SyncWorker",
    "asyncio",
    "run_parallel_all_async",
    "run_parallel_all_sync",
    "run_parallel_any_async",
    "run_parallel_any_sync",
]

