"""Async parallel execution helpers shared across runner implementations."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import inspect
from typing import Any, cast, Generic, TypeVar

T = TypeVar("T")

AsyncWorker = Callable[[], Awaitable[T]]
_SuccessCallback = Callable[[T], Awaitable[None]]
_FailureCallback = Callable[[BaseException], Awaitable[None]]

RetryDirective = float | tuple[int, float] | None


def _normalize_retry_directive(directive: RetryDirective) -> tuple[int | None, float | None]:
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


class _AsyncParallelExecutor(Generic[T]):
    def __init__(
        self,
        workers: Sequence[AsyncWorker[T]],
        *,
        max_concurrency: int | None,
        max_attempts: int | None,
        on_retry: Callable[[int, int, BaseException], Awaitable[RetryDirective] | RetryDirective]
        | None,
    ) -> None:
        from .parallel_exec import _normalize_concurrency

        limit = _normalize_concurrency(len(workers), max_concurrency)
        self._semaphore = asyncio.Semaphore(limit)
        self._max_attempts = max_attempts
        self._on_retry = on_retry
        self._attempts_lock = asyncio.Lock()
        self._attempts_used = 0

    async def _reserve_attempt(self) -> bool:
        async with self._attempts_lock:
            if self._max_attempts is not None and self._attempts_used >= self._max_attempts:
                return False
            self._attempts_used += 1
            return True

    async def _maybe_retry(self, index: int, attempt: int, exc: BaseException) -> tuple[int, bool]:
        if self._on_retry is None:
            return attempt, False
        directive = self._on_retry(index, attempt, exc)
        awaited = await _resolve_retry_directive(directive)
        next_attempt, delay = _normalize_retry_directive(awaited)
        if delay is not None and delay >= 0:
            if next_attempt is not None:
                attempt = max(next_attempt - 1, attempt)
            if delay > 0:
                await asyncio.sleep(delay)
            return attempt, True
        return attempt, False

    async def run_worker(
        self,
        index: int,
        worker: AsyncWorker[T],
        *,
        on_success: _SuccessCallback,
        on_failure: _FailureCallback,
        propagate_failure: bool,
    ) -> None:
        attempt = 0
        while await self._reserve_attempt():
            attempt += 1
            try:
                async with self._semaphore:
                    result = await worker()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                attempt, should_retry = await self._maybe_retry(index, attempt, exc)
                if should_retry:
                    continue
                await on_failure(exc)
                if propagate_failure:
                    raise
                return
            await on_success(result)
            return
        final_exc: BaseException
        if propagate_failure:
            from .parallel_exec import ParallelExecutionError

            final_exc = ParallelExecutionError("max attempts exhausted")
        else:
            final_exc = RuntimeError("max attempts exhausted")
        await on_failure(final_exc)
        if propagate_failure:
            raise final_exc


async def run_parallel_any_async(
    workers: Sequence[AsyncWorker[T]],
    *,
    max_concurrency: int | None = None,
    max_attempts: int | None = None,
    on_retry: Callable[[int, int, BaseException], Awaitable[RetryDirective] | RetryDirective]
        | None = None,
    on_cancelled: Callable[[Sequence[int]], None] | None = None,
) -> T:
    """Async variant of :func:`run_parallel_any_sync` with retry support."""
    if not workers:
        raise ValueError("workers must not be empty")
    from .parallel_exec import ParallelExecutionError

    executor = _AsyncParallelExecutor(
        workers,
        max_concurrency=max_concurrency,
        max_attempts=max_attempts,
        on_retry=on_retry,
    )
    winner: asyncio.Future[T] = asyncio.get_running_loop().create_future()
    failure_lock = asyncio.Lock()
    failures = 0

    async def _on_success(result: T) -> None:
        if not winner.done():
            winner.set_result(result)

    async def _on_failure(exc: BaseException) -> None:  # noqa: ARG001
        nonlocal failures
        async with failure_lock:
            failures += 1
            if failures == len(workers) and not winner.done():
                winner.set_exception(ParallelExecutionError("all workers failed"))

    task_pairs = [
        (
            idx,
            asyncio.create_task(
                executor.run_worker(
                    idx,
                    worker,
                    on_success=_on_success,
                    on_failure=_on_failure,
                    propagate_failure=False,
                )
            ),
        )
        for idx, worker in enumerate(workers)
    ]
    try:
        return await winner
    finally:
        for _, task in task_pairs:
            task.cancel()
        results = await asyncio.gather(
            *(task for _, task in task_pairs), return_exceptions=True
        )
        if on_cancelled is not None:
            cancelled = [
                index
                for (index, _), outcome in zip(task_pairs, results, strict=False)
                if isinstance(outcome, asyncio.CancelledError)
            ]
            if cancelled:
                on_cancelled(tuple(sorted(cancelled)))


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
    executor = _AsyncParallelExecutor(
        workers,
        max_concurrency=max_concurrency,
        max_attempts=max_attempts,
        on_retry=on_retry,
    )
    responses: list[T | None] = [None] * len(workers)

    async def _noop_failure(_: BaseException) -> None:
        return None

    def _success_factory(idx: int) -> _SuccessCallback:
        async def _on_success(value: T) -> None:
            responses[idx] = value

        return _on_success

    tasks = [
        asyncio.create_task(
            executor.run_worker(
                idx,
                worker,
                on_success=_success_factory(idx),
                on_failure=_noop_failure,
                propagate_failure=True,
            )
        )
        for idx, worker in enumerate(workers)
    ]
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
    "RetryDirective",
    "_AsyncParallelExecutor",
    "run_parallel_any_async",
    "run_parallel_all_async",
]
