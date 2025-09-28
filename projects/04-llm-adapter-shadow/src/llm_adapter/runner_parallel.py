"""Parallel and consensus orchestration helpers for runner implementations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
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
    score: float
    reason: str


def _extract_weight(response: ProviderResponse) -> float:
    raw = response.raw
    if isinstance(raw, Mapping):
        weight = raw.get("weight")
        if isinstance(weight, (int, float)):
            return float(weight)
    return 1.0

def compute_consensus(
    responses: Iterable[ProviderResponse], *, config: ConsensusConfig | None = None
) -> ConsensusResult:
    collected = list(responses)
    if not collected:
        raise ValueError("responses must not be empty")
    cfg = config or ConsensusConfig()
    groups: dict[str, list[ProviderResponse]] = {}
    for response in collected:
        groups.setdefault(response.text.strip(), []).append(response)
    if cfg.strategy == "majority":
        score_fn = lambda group: float(len(group))
    elif cfg.strategy == "weighted":
        score_fn = lambda group: float(sum(_extract_weight(resp) for resp in group))
    else:
        raise ValueError(f"unsupported consensus strategy: {cfg.strategy}")
    scores = {text: score_fn(group) for text, group in groups.items()}
    top_score = max(scores.values())
    tied_texts = [text for text, score in scores.items() if score == top_score]
    quorum = cfg.quorum or len(collected)
    if max(len(groups[text]) for text in tied_texts) < quorum:
        raise ParallelExecutionError("consensus quorum not reached")
    if len(tied_texts) == 1:
        text = tied_texts[0]
        return ConsensusResult(groups[text][0], len(groups[text]), top_score, f"strategy={cfg.strategy}")
    if cfg.tie_breaker == "latency":
        metric = lambda resp: resp.latency_ms
    elif cfg.tie_breaker == "cost":
        metric = lambda resp: resp.token_usage.total
    elif cfg.tie_breaker is None:
        raise ParallelExecutionError("consensus tie unresolved")
    else:
        raise ValueError(f"unsupported tie breaker: {cfg.tie_breaker}")
    text = min(tied_texts, key=lambda t: min(metric(resp) for resp in groups[t]))
    winner = min(groups[text], key=metric)
    return ConsensusResult(winner, len(groups[text]), top_score, f"strategy={cfg.strategy},tie_breaker={cfg.tie_breaker}")

def _build_schema_validator(schema: str) -> Callable[[ProviderResponse], bool]:
    data = json.loads(schema)
    required = data.get("required", []) if isinstance(data, dict) else []
    expect_object = isinstance(data, dict) and data.get("type") == "object"

    def _validate(response: ProviderResponse) -> bool:
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            return False
        if expect_object and not isinstance(payload, dict):
            return False
        return all(field in payload for field in required)

    return _validate

def resolve_consensus(
    responses: Sequence[ProviderResponse],
    *,
    config: ConsensusConfig | None = None,
    judge: Callable[[Sequence[ProviderResponse]], ProviderResponse | None] | None = None,
) -> ConsensusResult:
    cfg = config or ConsensusConfig()
    remaining = list(responses)
    validator = _build_schema_validator(cfg.schema) if cfg.schema else None
    rounds = cfg.max_rounds or 1
    last_error: ParallelExecutionError | None = None
    for _ in range(rounds):
        if validator is not None:
            remaining = [response for response in remaining if validator(response)]
        if not remaining:
            raise ParallelExecutionError("no responses after validation")
        try:
            return compute_consensus(remaining, config=cfg)
        except ParallelExecutionError as exc:
            last_error = exc
            if cfg.judge is None:
                continue
            if judge is None:
                raise ValueError("judge callable required when judge is configured")
            judged = judge(remaining)
            if judged is None:
                continue
            return ConsensusResult(
                response=judged,
                votes=0,
                score=0.0,
                reason=f"judge={cfg.judge}",
            )
    if last_error is not None:
        raise last_error
    raise ParallelExecutionError("consensus resolution failed")


__all__ = [
    "ParallelExecutionError",
    "ConsensusResult",
    "compute_consensus",
    "resolve_consensus",
    "run_parallel_all_async",
    "run_parallel_all_sync",
    "run_parallel_any_async",
    "run_parallel_any_sync",
]
