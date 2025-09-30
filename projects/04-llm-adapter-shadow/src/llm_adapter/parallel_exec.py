"""Parallel execution helpers shared across runner implementations."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from concurrent.futures import (
    as_completed,
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass
import inspect
from typing import Any, cast, Generic, TypeVar

T = TypeVar("T")
S = TypeVar("S")


SyncWorker = Callable[[], T]
AsyncWorker = Callable[[], Awaitable[T]]

RetryDirective = float | tuple[int, float] | None


class ParallelExecutionError(RuntimeError):
    """Raised when all parallel workers fail to produce a response."""

    def __init__(
        self,
        message: str,
        *,
        failures: Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.failures: list[dict[str, str]] | None
        if failures is None:
            self.failures = None
        else:
            self.failures = [dict(detail) for detail in failures]


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
    workers: Sequence[SyncWorker[T]], *, max_concurrency: int | None = None
) -> T:
    """Execute workers concurrently until the first success."""

    if not workers:
        raise ValueError("workers must not be empty")
    max_workers = _normalize_concurrency(len(workers), max_concurrency)
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        worker_iter = iter(enumerate(workers))
        future_map: dict[Future[T], int] = {}

        def _submit_next() -> None:
            try:
                idx, worker = next(worker_iter)
            except StopIteration:
                return
            future_map[executor.submit(worker)] = idx

        for _ in range(max_workers):
            _submit_next()

        while future_map:
            done, _ = wait(future_map, return_when=FIRST_COMPLETED)
            for future in done:
                future_map.pop(future, None)
                try:
                    result = future.result()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    _submit_next()
                    continue
                for pending in list(future_map):
                    pending.cancel()
                return result
    raise ParallelExecutionError("all workers failed") from errors[-1] if errors else None


def _normalize_retry_directive(
    directive: RetryDirective,
) -> tuple[int | None, float | None]:
    if directive is None:
        return None, None
    if isinstance(directive, tuple):
        next_attempt, delay_value = directive
    else:
        next_attempt, delay_value = None, directive
    delay_normalized = None if delay_value is None else float(delay_value)
    return next_attempt, delay_normalized


async def _resolve_retry_directive(
    directive: Awaitable[RetryDirective] | RetryDirective,
) -> RetryDirective:
    if inspect.isawaitable(directive):
        awaited_directive = await cast(Awaitable[Any], directive)
    else:
        awaited_directive = directive
    return cast(RetryDirective, awaited_directive)


async def run_parallel_any_async(
    workers: Sequence[AsyncWorker[T]],
    *,
    max_concurrency: int | None = None,
    max_attempts: int | None = None,
    on_retry: Callable[[int, int, BaseException], Awaitable[RetryDirective] | RetryDirective]
    | None = None,
) -> T:
    """Async variant of :func:`run_parallel_any_sync` with retry support."""

    if not workers:
        raise ValueError("workers must not be empty")
    limit = _normalize_concurrency(len(workers), max_concurrency)
    semaphore = asyncio.Semaphore(limit)
    winner: asyncio.Future[T] = asyncio.get_running_loop().create_future()
    attempts_lock = asyncio.Lock()
    failure_lock = asyncio.Lock()
    attempts_used = failures = 0

    async def _reserve_attempt() -> bool:
        nonlocal attempts_used
        async with attempts_lock:
            if max_attempts is not None and attempts_used >= max_attempts:
                return False
            attempts_used += 1
            return True

    async def _record_failure(error: BaseException | None) -> None:
        nonlocal failures
        async with failure_lock:
            failures += 1
            if failures == len(workers) and not winner.done():
                winner.set_exception(ParallelExecutionError("all workers failed"))

    async def runner(index: int, worker: AsyncWorker[T]) -> None:
        attempt = 0
        while await _reserve_attempt():
            attempt += 1
            try:
                async with semaphore:
                    result = await worker()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                delay: float | None = None
                next_attempt: int | None = None
                if on_retry is not None:
                    directive = on_retry(index, attempt, exc)
                    awaited = await _resolve_retry_directive(directive)
                    next_attempt, delay = _normalize_retry_directive(awaited)
                if delay is not None and delay >= 0:
                    if next_attempt is not None:
                        attempt = max(next_attempt - 1, attempt)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue
                await _record_failure(exc)
                return
            if not winner.done():
                winner.set_result(result)
            return
        await _record_failure(RuntimeError("max attempts exhausted"))

    tasks = [asyncio.create_task(runner(idx, worker)) for idx, worker in enumerate(workers)]
    try:
        return await winner
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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


async def run_parallel_all_async(
    workers: Sequence[AsyncWorker[T]],
    *,
    max_concurrency: int | None = None,
    max_attempts: int | None = None,
    on_retry: Callable[[int, int, BaseException], Awaitable[RetryDirective] | RetryDirective]
    | None = None,
) -> list[T]:
    """Async variant of :func:`run_parallel_all_sync`."""

    if not workers:
        raise ValueError("workers must not be empty")
    limit = _normalize_concurrency(len(workers), max_concurrency)
    semaphore = asyncio.Semaphore(limit)
    responses: list[T | None] = [None] * len(workers)
    attempts_lock = asyncio.Lock()
    attempts_used = 0

    async def _reserve_attempt() -> bool:
        nonlocal attempts_used
        async with attempts_lock:
            if max_attempts is not None and attempts_used >= max_attempts:
                return False
            attempts_used += 1
            return True

    async def runner(index: int, worker: AsyncWorker[T]) -> None:
        attempt = 0
        while await _reserve_attempt():
            attempt += 1
            try:
                async with semaphore:
                    responses[index] = await worker()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                delay: float | None = None
                next_attempt: int | None = None
                if on_retry is not None:
                    directive = on_retry(index, attempt, exc)
                    awaited = await _resolve_retry_directive(directive)
                    next_attempt, delay = _normalize_retry_directive(awaited)
                if delay is not None and delay >= 0:
                    if next_attempt is not None:
                        attempt = max(next_attempt - 1, attempt)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue
                raise
            else:
                return
        raise ParallelExecutionError("max attempts exhausted")

    tasks = [asyncio.create_task(runner(idx, worker)) for idx, worker in enumerate(workers)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return cast(list[T], responses)


__all__ = [
    "AsyncWorker",
    "ParallelAllResult",
    "ParallelExecutionError",
    "RetryDirective",
    "SyncWorker",
    "run_parallel_all_async",
    "run_parallel_all_sync",
    "run_parallel_any_async",
    "run_parallel_any_sync",
]

