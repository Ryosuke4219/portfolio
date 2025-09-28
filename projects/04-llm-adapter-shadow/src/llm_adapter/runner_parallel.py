"""Parallel and consensus orchestration helpers for runner implementations."""

from __future__ import annotations

import asyncio
import importlib
import json
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

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


async def run_parallel_any_async(
    workers: Sequence[AsyncWorker[T]],
    *,
    max_concurrency: int | None = None,
    max_attempts: int | None = None,
    on_retry: Callable[[int, int, BaseException], Awaitable[float | None] | float | None]
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
                if on_retry is not None:
                    maybe_delay = on_retry(index, attempt, exc)
                    if asyncio.iscoroutine(maybe_delay):
                        maybe_delay = await cast(Awaitable[float | None], maybe_delay)
                    delay = cast(float | None, maybe_delay)
                if delay is not None and delay >= 0:
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
    tie_breaker_selected: str | None
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
    best_score: float = 0.0
    latency: int = 0
    cost: float = 0.0

    def record(self, index: int, response: ProviderResponse) -> None:
        self.entries.append((index, response))
        self.votes += 1
        value = _extract_score(response)
        self.score += value
        self.best_score = value if self.votes == 1 else max(self.best_score, value)
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
        if isinstance(value, int | float):
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
    return cast(Callable[[Sequence[ProviderResponse]], Any], judge)


def _select_candidates(
    strategy: str, candidates: Mapping[str, _Candidate]
) -> tuple[list[_Candidate], float, dict[str, float] | None]:
    normalized = strategy.strip().lower()
    if normalized == "majority":
        pivot_votes = max(candidate.votes for candidate in candidates.values())
        pool = [
            candidate
            for candidate in candidates.values()
            if candidate.votes == pivot_votes
        ]
        return pool, float(pivot_votes), None
    if normalized == "weighted":
        scores = {text: candidate.score for text, candidate in candidates.items()}
        pivot_score = max(scores.values())
        pool = [
            candidate
            for candidate in candidates.values()
            if math.isclose(
                candidate.score, pivot_score, rel_tol=1e-9, abs_tol=1e-9
            )
        ]
        return pool, float(pivot_score), scores
    if normalized == "max_score":
        scores = {text: candidate.best_score for text, candidate in candidates.items()}
        pivot_score = max(scores.values())
        pool = [
            candidate
            for candidate in candidates.values()
            if math.isclose(
                candidate.best_score, pivot_score, rel_tol=1e-9, abs_tol=1e-9
            )
        ]
        return pool, float(pivot_score), scores
    raise ValueError(f"unsupported consensus strategy: {strategy!r}")


def _tie_break_by_latency(candidates: Sequence[_Candidate]) -> tuple[list[_Candidate], str]:
    best = min(candidate.latency for candidate in candidates)
    narrowed = [candidate for candidate in candidates if candidate.latency == best]
    return narrowed, f"latency(min={best})"


def _tie_break_by_cost(candidates: Sequence[_Candidate]) -> tuple[list[_Candidate], str]:
    best_cost = min(candidate.cost for candidate in candidates)
    narrowed = [candidate for candidate in candidates if candidate.cost == best_cost]
    return narrowed, "cost(min)"


def _apply_tie_breaker(
    name: str, candidates: Sequence[_Candidate]
) -> tuple[list[_Candidate], str, str]:
    normalized = name.strip().lower()
    handlers: dict[str, Callable[[Sequence[_Candidate]], tuple[list[_Candidate], str]]] = {
        "latency": _tie_break_by_latency,
        "cost": _tie_break_by_cost,
    }
    handler = handlers.get(normalized)
    if handler is None:
        raise ValueError(f"unknown tie_breaker: {name!r}")
    narrowed, reason = handler(candidates)
    return narrowed, reason, normalized


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


def validate_consensus_schema(
    responses: Sequence[ProviderResponse], schema: str | None
) -> tuple[list[tuple[int, ProviderResponse]], dict[int, str], bool]:
    if not schema:
        return list(enumerate(responses)), {}, False

    try:
        schema_spec = json.loads(schema)
    except json.JSONDecodeError as exc:  # pragma: no cover - config error
        raise ValueError("invalid consensus schema") from exc
    if not isinstance(schema_spec, Mapping):
        raise ValueError("invalid consensus schema")

    valid_entries: list[tuple[int, ProviderResponse]] = []
    failures: dict[int, str] = {}
    expected_type = schema_spec.get("type")
    required_fields = [str(field) for field in schema_spec.get("required", [])]

    for index, response in enumerate(responses):
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError as exc:
            failures[index] = f"invalid json: {exc.msg}"
            continue
        if expected_type == "object" and not isinstance(parsed, Mapping):
            failures[index] = "expected object"
            continue
        missing = [field for field in required_fields if field not in parsed]
        if missing:
            failures[index] = f"missing keys: {', '.join(missing)}"
            continue
        valid_entries.append((index, response))

    return valid_entries, failures, True


def invoke_consensus_judge(
    judge: str, candidates: Sequence[_Candidate]
) -> tuple[str, float | None]:
    return _invoke_judge(_load_judge(judge), candidates)


def compute_consensus(
    responses: Iterable[ProviderResponse], *, config: ConsensusConfig | None = None
) -> ConsensusResult:
    """Return the majority response according to ``config``."""

    collected = list(responses)
    if not collected:
        raise ValueError("responses must not be empty")
    if config is None:
        config = ConsensusConfig()
    strategy = (config.strategy or "majority").strip()
    tie_breaker = (config.tie_breaker or "").strip().lower() or None
    if tie_breaker is not None and tie_breaker not in {"latency", "cost"}:
        raise ValueError(f"unsupported tie_breaker: {config.tie_breaker!r}")

    valid_entries, schema_failures, schema_checked = validate_consensus_schema(
        collected, config.schema
    )

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
    if not tally:
        raise ParallelExecutionError("consensus tally is empty")

    pool, winner_score, score_map = _select_candidates(strategy, candidates)

    tie_break_applied = len(pool) > 1
    rounds = 1
    tie_break_reason = None
    tie_breaker_selected: str | None = None
    judge_name: str | None = None
    judge_score: float | None = None
    remaining = pool
    max_rounds = config.max_rounds

    def _next_round() -> None:
        nonlocal rounds
        if max_rounds is not None and rounds >= max_rounds:
            raise ParallelExecutionError("consensus max_rounds exhausted")
        rounds += 1

    if tie_break_applied and tie_breaker is not None:
        _next_round()
        remaining, tie_break_reason, tie_breaker_selected = _apply_tie_breaker(
            tie_breaker, remaining
        )

    if len(remaining) > 1 and config.judge:
        _next_round()
        judge_name = config.judge
        choice, judge_score = invoke_consensus_judge(judge_name, remaining)
        for candidate in remaining:
            if candidate.text == choice:
                remaining = [candidate]
                break
        else:  # pragma: no cover - defensive guard
            raise ParallelExecutionError("judge returned unknown choice")

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
        tie_breaker_selected=tie_breaker_selected,
        winner_score=winner_score,
        abstained=len(collected) - len(valid_entries),
        rounds=rounds,
        schema_checked=schema_checked,
        schema_failures=schema_failures,
        judge_name=judge_name,
        judge_score=judge_score,
        scores=score_map,
    )


__all__ = [
    "ParallelExecutionError",
    "ConsensusResult",
    "invoke_consensus_judge",
    "validate_consensus_schema",
    "compute_consensus",
    "run_parallel_all_async",
    "run_parallel_all_sync",
    "run_parallel_any_async",
    "run_parallel_any_sync",
]
