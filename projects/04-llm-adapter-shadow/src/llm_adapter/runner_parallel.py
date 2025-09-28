"""Parallel and consensus orchestration helpers for runner implementations."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from dataclasses import dataclass
from typing import TypeVar

from .provider_spi import ProviderResponse
from .runner_config import ConsensusConfig

T = TypeVar("T")


SyncWorker = Callable[[], T]
AsyncWorker = Callable[[], Awaitable[T]]


class ParallelExecutionError(RuntimeError):
    """Raised when all parallel workers fail to produce a response."""


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
        future_map = {executor.submit(worker): idx for idx, worker in enumerate(workers)}
        while future_map:
            done, _ = wait(future_map, return_when=FIRST_COMPLETED)
            for future in done:
                future_map.pop(future, None)
                try:
                    result = future.result()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    continue
                for pending in future_map:
                    pending.cancel()
                return result
    raise ParallelExecutionError("all workers failed") from errors[-1] if errors else None


async def run_parallel_any_async(
    workers: Sequence[AsyncWorker[T]], *, max_concurrency: int | None = None
) -> T:
    """Async variant of :func:`run_parallel_any_sync`."""

    if not workers:
        raise ValueError("workers must not be empty")
    limit = _normalize_concurrency(len(workers), max_concurrency)
    semaphore = asyncio.Semaphore(limit)
    winner: asyncio.Future[T] = asyncio.get_running_loop().create_future()
    errors: list[BaseException] = []

    async def runner(worker: AsyncWorker[T]) -> None:
        nonlocal errors
        try:
            async with semaphore:
                result = await worker()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            if len(errors) == len(workers) and not winner.done():
                winner.set_exception(ParallelExecutionError("all workers failed"))
            return
        if not winner.done():
            winner.set_result(result)

    tasks = [asyncio.create_task(runner(worker)) for worker in workers]
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
    workers: Sequence[AsyncWorker[T]], *, max_concurrency: int | None = None
) -> list[T]:
    """Async variant of :func:`run_parallel_all_sync`."""

    if not workers:
        raise ValueError("workers must not be empty")
    limit = _normalize_concurrency(len(workers), max_concurrency)
    semaphore = asyncio.Semaphore(limit)
    responses: list[T] = [None] * len(workers)  # type: ignore[list-item]

    async def runner(index: int, worker: AsyncWorker[T]) -> None:
        async with semaphore:
            responses[index] = await worker()

    tasks = [asyncio.create_task(runner(idx, worker)) for idx, worker in enumerate(workers)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return responses


@dataclass(slots=True)
class ConsensusResult:
    response: ProviderResponse
    votes: int


def compute_consensus(
    responses: Iterable[ProviderResponse], *, config: ConsensusConfig | None = None
) -> ConsensusResult:
    """Return the majority response according to ``config``."""

    collected = list(responses)
    if not collected:
        raise ValueError("responses must not be empty")
    if config is None:
        config = ConsensusConfig()
    quorum = config.quorum or len(collected)
    counter = Counter(response.text.strip() for response in collected)
    top_text, votes = counter.most_common(1)[0]
    if votes < quorum:
        raise ParallelExecutionError("consensus quorum not reached")
    for response in collected:
        if response.text.strip() == top_text:
            return ConsensusResult(response=response, votes=votes)
    raise RuntimeError("consensus resolution failed")


__all__ = [
    "ParallelExecutionError",
    "ConsensusResult",
    "compute_consensus",
    "run_parallel_all_async",
    "run_parallel_all_sync",
    "run_parallel_any_async",
    "run_parallel_any_sync",
]
