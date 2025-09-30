"""Consensus orchestration helpers for runner implementations."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import importlib
import json
import math
from typing import Any, cast

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
        if isinstance(value, (int, float)):  # noqa: UP038 - tuple form required
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
    normalized_input = strategy.strip().lower()
    aliases = {
        "majority_vote": "majority",
        "weighted_vote": "weighted",
    }
    normalized = aliases.get(normalized_input, normalized_input)
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


def _tie_break_by_stable_order(
    candidates: Sequence[_Candidate],
) -> tuple[list[_Candidate], str]:
    indexed = [
        (candidate, min(index for index, _ in candidate.entries)) for candidate in candidates
    ]
    best_index = min(position for _, position in indexed)
    narrowed = [candidate for candidate, position in indexed if position == best_index]
    return narrowed, f"stable_order(first_index={best_index})"


def _normalize_tie_breaker_name(name: str) -> str:
    normalized_input = name.strip().lower()
    aliases = {
        "min_latency": "latency",
        "min_cost": "cost",
    }
    normalized = aliases.get(normalized_input, normalized_input)
    valid = {"latency", "cost", "stable_order"}
    if normalized not in valid:
        raise ValueError(f"unknown tie_breaker: {name!r}")
    return normalized


def _apply_tie_breaker(
    name: str, candidates: Sequence[_Candidate]
) -> tuple[list[_Candidate], str, str]:
    normalized = _normalize_tie_breaker_name(name)
    handlers: dict[str, Callable[[Sequence[_Candidate]], tuple[list[_Candidate], str]]] = {
        "latency": _tie_break_by_latency,
        "cost": _tie_break_by_cost,
        "stable_order": _tie_break_by_stable_order,
    }
    handler = handlers[normalized]
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
    tie_breaker_value = (config.tie_breaker or "").strip()
    normalized_tie_breaker = (
        _normalize_tie_breaker_name(tie_breaker_value) if tie_breaker_value else None
    )

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

    if tie_break_applied:
        sequence = (
            [normalized_tie_breaker]
            if normalized_tie_breaker is not None
            else ["latency", "cost", "stable_order"]
        )
        for breaker in sequence:
            if len(remaining) <= 1:
                break
            _next_round()
            remaining, tie_break_reason, tie_breaker_selected = _apply_tie_breaker(
                breaker, remaining
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
]
