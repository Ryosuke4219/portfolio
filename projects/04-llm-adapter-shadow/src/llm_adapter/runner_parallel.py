"""Consensus orchestration helpers for runner implementations."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import importlib
from typing import Any, cast

from .consensus_candidates import (
    _apply_tie_breaker,
    _Candidate,
    _normalize_candidate_text,
    CandidateSet,
    validate_consensus_schema,
)
from .parallel_exec import ParallelExecutionError
from .provider_spi import ProviderResponse
from .runner_config import ConsensusConfig


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


def _load_judge(path: str) -> Callable[[Sequence[ProviderResponse]], Any]:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError("judge must be defined as 'module:callable'")
    module = importlib.import_module(module_name)
    judge = getattr(module, attr, None)
    if not callable(judge):
        raise ValueError(f"judge callable {path!r} is not callable")
    return cast(Callable[[Sequence[ProviderResponse]], Any], judge)


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

    candidate_set = CandidateSet.from_entries(valid_entries)
    if candidate_set.is_empty():
        raise ParallelExecutionError("consensus tally is empty")

    tally = candidate_set.tally()

    pool, winner_score, score_map = candidate_set.select(strategy)

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
    "_normalize_candidate_text",
    "validate_consensus_schema",
    "compute_consensus",
]
