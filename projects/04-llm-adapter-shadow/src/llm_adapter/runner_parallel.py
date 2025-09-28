"""Parallel and consensus orchestration helpers for runner implementations."""

from __future__ import annotations

import asyncio
import importlib
import json
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from dataclasses import dataclass, field
from typing import Any, TypeVar

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
    tally: dict[str, int]
    total_voters: int
    strategy: str
    min_votes: int | None
    score_threshold: float | None
    tie_breaker: str | None
    tie_break_applied: bool
    tie_break_reason: str | None
    winner_score: float
    abstained: int
    rounds: int
    schema_checked: bool
    schema_failures: dict[int, str]
    judge_name: str | None
    judge_score: float | None
    scores: dict[str, float] | None


@dataclass(slots=True)
class _Candidate:
    text: str
    entries: list[tuple[int, ProviderResponse]] = field(default_factory=list)
    votes: int = 0
    score: float = 0.0
    latency: int = 0
    cost: float = 0.0

    def record(self, index: int, response: ProviderResponse) -> None:
        self.entries.append((index, response))
        self.votes += 1
        self.score += _extract_score(response)
        latency = int(response.latency_ms)
        cost = float((response.tokens_in or 0) + (response.tokens_out or 0))
        self.latency = latency if self.votes == 1 else min(self.latency, latency)
        self.cost = cost if self.votes == 1 else min(self.cost, cost)

    @property
    def primary(self) -> ProviderResponse:
        return min(self.entries, key=lambda item: item[0])[1]


def _extract_score(response: ProviderResponse) -> float:
    raw = response.raw
    if isinstance(raw, Mapping):
        value = raw.get("score")
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _load_judge(path: str) -> Callable[[Sequence[ProviderResponse]], Any]:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError("judge must be defined as 'module:callable'")
    module = importlib.import_module(module_name)
    judge = getattr(module, attr, None)
    if not callable(judge):
        raise ValueError(f"judge callable {path!r} is not callable")
    return judge


def _apply_tie_breaker(
    name: str, candidates: Sequence[_Candidate]
) -> tuple[list[_Candidate], str]:
    normalized = name.strip().lower()
    if normalized == "latency":
        best = min(candidate.latency for candidate in candidates)
        narrowed = [candidate for candidate in candidates if candidate.latency == best]
        return narrowed, f"latency(min={best})"
    if normalized == "cost":
        best_cost = min(candidate.cost for candidate in candidates)
        narrowed = [candidate for candidate in candidates if candidate.cost == best_cost]
        return narrowed, "cost(min)"
    raise ValueError(f"unknown tie_breaker: {name!r}")


def _invoke_judge(
    judge: Callable[[Sequence[ProviderResponse]], Any],
    candidates: Sequence[_Candidate],
) -> tuple[str, float | None]:
    payload = judge([candidate.primary for candidate in candidates])
    if isinstance(payload, Mapping):
        choice, score = max(payload.items(), key=lambda item: float(item[1]))
        return str(choice).strip(), float(score)
    if isinstance(payload, tuple) and len(payload) == 2:
        choice, score = payload
        return str(choice).strip(), float(score)
    if isinstance(payload, str):
        return payload.strip(), None
    raise TypeError("judge must return str, (choice, score) or mapping of scores")


def compute_consensus(
    responses: Iterable[ProviderResponse], *, config: ConsensusConfig | None = None
) -> ConsensusResult:
    """Return the majority response according to ``config``."""

    collected = list(responses)
    if not collected:
        raise ValueError("responses must not be empty")
    if config is None:
        config = ConsensusConfig()
    strategy = (config.strategy or "majority").strip().lower()
    if strategy not in {"majority", "weighted"}:
        raise ValueError(f"unsupported consensus strategy: {config.strategy!r}")
    tie_breaker = (config.tie_breaker or "").strip().lower() or None
    if tie_breaker is not None and tie_breaker not in {"latency", "cost"}:
        raise ValueError(f"unsupported tie_breaker: {config.tie_breaker!r}")

    schema_spec: dict[str, Any] | None = None
    if config.schema:
        try:
            schema_spec = json.loads(config.schema)
        except json.JSONDecodeError as exc:  # pragma: no cover - config error
            raise ValueError("invalid consensus schema") from exc

    valid_entries: list[tuple[int, ProviderResponse]] = []
    schema_failures: dict[int, str] = {}
    for index, response in enumerate(collected):
        if schema_spec is None:
            valid_entries.append((index, response))
            continue
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError as exc:
            schema_failures[index] = f"invalid json: {exc.msg}"
            continue
        expected_type = schema_spec.get("type")
        if expected_type == "object" and not isinstance(parsed, Mapping):
            schema_failures[index] = "expected object"
            continue
        required = schema_spec.get("required") or []
        missing = [field for field in required if field not in parsed]
        if missing:
            schema_failures[index] = f"missing keys: {', '.join(map(str, missing))}"
            continue
        valid_entries.append((index, response))

    if not valid_entries:
        raise ParallelExecutionError("all responses failed schema validation")

    candidates: dict[str, _Candidate] = {}
    for index, response in valid_entries:
        key = response.text.strip()
        candidate = candidates.get(key)
        if candidate is None:
            candidate = _Candidate(text=key)
            candidates[key] = candidate
        candidate.record(index, response)

    tally = {text: candidate.votes for text, candidate in candidates.items()}
    scores = {text: candidate.score for text, candidate in candidates.items()}
    if not tally:
        raise ParallelExecutionError("consensus tally is empty")

    if strategy == "majority":
        pivot = max(tally.values())
        pool = [candidate for candidate in candidates.values() if candidate.votes == pivot]
        winner_score = float(pivot)
    else:
        pivot = max(scores.values())
        pool = [
            candidate
            for candidate in candidates.values()
            if math.isclose(candidate.score, pivot, rel_tol=1e-9, abs_tol=1e-9)
        ]
        winner_score = float(pivot)

    tie_break_applied = len(pool) > 1
    rounds = 1
    tie_break_reason = None
    judge_name: str | None = None
    judge_score: float | None = None
    remaining = pool
    max_rounds = config.max_rounds

    if tie_break_applied and tie_breaker is not None:
        if max_rounds is not None and rounds >= max_rounds:
            raise ParallelExecutionError("consensus max_rounds exhausted")
        remaining, tie_break_reason = _apply_tie_breaker(tie_breaker, remaining)
        rounds += 1

    if len(remaining) > 1 and config.judge:
        if max_rounds is not None and rounds >= max_rounds:
            raise ParallelExecutionError("consensus max_rounds exhausted")
        judge_name = config.judge
        judge_callable = _load_judge(judge_name)
        choice, judge_score = _invoke_judge(judge_callable, remaining)
        for candidate in remaining:
            if candidate.text == choice:
                remaining = [candidate]
                break
        else:  # pragma: no cover - defensive guard
            raise ParallelExecutionError("judge returned unknown choice")
        rounds += 1

    if len(remaining) > 1:
        raise ParallelExecutionError("consensus tie could not be resolved")

    winner = remaining[0]
    votes = winner.votes
    quorum = config.quorum or len(valid_entries)
    if votes < quorum:
        raise ParallelExecutionError("consensus quorum not reached")

    return ConsensusResult(
        response=winner.primary,
        votes=votes,
        tally=tally,
        total_voters=len(collected),
        strategy=config.strategy,
        min_votes=config.quorum,
        score_threshold=None,
        tie_breaker=config.tie_breaker,
        tie_break_applied=tie_break_applied,
        tie_break_reason=tie_break_reason,
        winner_score=winner_score,
        abstained=len(collected) - len(valid_entries),
        rounds=rounds,
        schema_checked=schema_spec is not None,
        schema_failures=schema_failures,
        judge_name=judge_name,
        judge_score=judge_score,
        scores=scores if strategy == "weighted" else None,
    )


__all__ = [
    "ParallelExecutionError",
    "ConsensusResult",
    "compute_consensus",
    "run_parallel_all_async",
    "run_parallel_all_sync",
    "run_parallel_any_async",
    "run_parallel_any_sync",
]
