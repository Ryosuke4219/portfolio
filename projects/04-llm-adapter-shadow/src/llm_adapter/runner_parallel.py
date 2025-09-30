"""Consensus orchestration helpers for runner implementations."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import importlib
import json
import math
from typing import Any, cast

from .parallel_exec import ParallelExecutionError
from .provider_spi import ProviderResponse, ProviderSPI
from .runner_config import (
    ConsensusConfig,
    ConsensusStrategy,
    ConsensusTieBreaker,
)


@dataclass(frozen=True, slots=True)
class ConsensusInput:
    provider: ProviderSPI
    response: ProviderResponse
    order: int


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
    normalized: str
    text: str
    raw_text: str
    entries: list[ConsensusInput] = field(default_factory=list)
    votes: int = 0
    weighted_votes: float = 0.0
    score: float = 0.0
    best_score: float = 0.0
    latency: int = 0
    cost: float = 0.0
    stable_order: int = 0

    def record(self, entry: ConsensusInput, weight: float) -> None:
        self.entries.append(entry)
        self.votes += 1
        self.weighted_votes += weight
        response = entry.response
        value = _extract_score(response)
        self.score += value
        self.best_score = value if self.votes == 1 else max(self.best_score, value)
        latency = int(response.latency_ms)
        cost = float((response.tokens_in or 0) + (response.tokens_out or 0))
        if self.votes == 1:
            self.latency = latency
            self.cost = cost
            self.stable_order = entry.order
        else:
            self.latency = min(self.latency, latency)
            self.cost = min(self.cost, cost)
            self.stable_order = min(self.stable_order, entry.order)

    @property
    def primary(self) -> ProviderResponse:
        return min(self.entries, key=lambda item: item.order).response


def _extract_score(response: ProviderResponse) -> float:
    raw = response.raw
    if isinstance(raw, Mapping):
        value = raw.get("score")
        if isinstance(value, (int, float)):  # noqa: UP038 - tuple form required
            return float(value)
    return 0.0


def _normalize_candidate_text(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "", stripped
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        normalized = " ".join(stripped.split()).lower()
        return normalized, stripped
    normalized = json.dumps(
        parsed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return normalized, stripped


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
    strategy: ConsensusStrategy, candidates: Mapping[str, _Candidate]
) -> tuple[list[_Candidate], float, dict[str, float] | None]:
    values = list(candidates.values())
    if strategy is ConsensusStrategy.MAJORITY_VOTE:
        pivot_votes = max(candidate.votes for candidate in values)
        pool = [candidate for candidate in values if candidate.votes == pivot_votes]
        return pool, float(pivot_votes), None
    if strategy is ConsensusStrategy.WEIGHTED_VOTE:
        scores = {candidate.text: candidate.weighted_votes for candidate in values}
        pivot_score = max(scores.values())
        pool = [
            candidate
            for candidate in values
            if math.isclose(
                candidate.weighted_votes, pivot_score, rel_tol=1e-9, abs_tol=1e-9
            )
        ]
        return pool, float(pivot_score), scores
    if strategy is ConsensusStrategy.MAX_SCORE:
        scores = {candidate.text: candidate.best_score for candidate in values}
        pivot_score = max(scores.values())
        pool = [
            candidate
            for candidate in values
            if math.isclose(
                candidate.best_score, pivot_score, rel_tol=1e-9, abs_tol=1e-9
            )
        ]
        return pool, float(pivot_score), scores
    raise ValueError(f"unsupported consensus strategy: {strategy!r}")


def _tie_break_by_latency(candidates: Sequence[_Candidate]) -> tuple[list[_Candidate], str]:
    best = min(candidate.latency for candidate in candidates)
    narrowed = [candidate for candidate in candidates if candidate.latency == best]
    return narrowed, f"min_latency(min={best})"


def _tie_break_by_cost(candidates: Sequence[_Candidate]) -> tuple[list[_Candidate], str]:
    best_cost = min(candidate.cost for candidate in candidates)
    narrowed = [candidate for candidate in candidates if candidate.cost == best_cost]
    return narrowed, f"min_cost(min={best_cost})"


def _tie_break_by_stable_order(
    candidates: Sequence[_Candidate],
) -> tuple[list[_Candidate], str]:
    best_order = min(candidate.stable_order for candidate in candidates)
    narrowed = [
        candidate for candidate in candidates if candidate.stable_order == best_order
    ]
    return narrowed, f"stable_order(index={best_order})"


def _apply_tie_breaker(
    name: ConsensusTieBreaker, candidates: Sequence[_Candidate]
) -> tuple[list[_Candidate], str]:
    if name is ConsensusTieBreaker.MIN_LATENCY:
        return _tie_break_by_latency(candidates)
    if name is ConsensusTieBreaker.MIN_COST:
        return _tie_break_by_cost(candidates)
    if name is ConsensusTieBreaker.STABLE_ORDER:
        return _tie_break_by_stable_order(candidates)
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


def validate_consensus_schema(
    entries: Sequence[ConsensusInput], schema: str | None
) -> tuple[list[ConsensusInput], dict[int, str], bool]:
    if not schema:
        return list(entries), {}, False

    try:
        schema_spec = json.loads(schema)
    except json.JSONDecodeError as exc:  # pragma: no cover - config error
        raise ValueError("invalid consensus schema") from exc
    if not isinstance(schema_spec, Mapping):
        raise ValueError("invalid consensus schema")

    valid_entries: list[ConsensusInput] = []
    failures: dict[int, str] = {}
    expected_type = schema_spec.get("type")
    required_fields = [str(field) for field in schema_spec.get("required", [])]

    for index, entry in enumerate(entries):
        try:
            parsed = json.loads(entry.response.text)
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
        valid_entries.append(entry)

    return valid_entries, failures, True


def invoke_consensus_judge(
    judge: str, candidates: Sequence[_Candidate]
) -> tuple[str, float | None]:
    return _invoke_judge(_load_judge(judge), candidates)


def compute_consensus(
    inputs: Iterable[ConsensusInput], *, config: ConsensusConfig | None = None
) -> ConsensusResult:
    """Return the majority response according to ``config``."""

    collected = list(inputs)
    if not collected:
        raise ValueError("responses must not be empty")
    if config is None:
        config = ConsensusConfig()

    strategy = config.strategy
    provider_weights = {
        name: float(weight)
        for name, weight in (config.provider_weights or {}).items()
    }

    valid_entries, schema_failures, schema_checked = validate_consensus_schema(
        collected, config.schema
    )

    if not valid_entries:
        raise ParallelExecutionError("all responses failed schema validation")

    candidates: dict[str, _Candidate] = {}
    for entry in valid_entries:
        normalized, display_text = _normalize_candidate_text(entry.response.text)
        candidate = candidates.get(normalized)
        if candidate is None:
            candidate = _Candidate(
                normalized=normalized,
                text=display_text,
                raw_text=entry.response.text,
            )
            candidates[normalized] = candidate
        provider_name = entry.provider.name()
        weight = provider_weights.get(provider_name, 1.0)
        candidate.record(entry, weight)

    tally = {candidate.text: candidate.votes for candidate in candidates.values()}
    if not tally:
        raise ParallelExecutionError("consensus tally is empty")

    pool, winner_score, score_map = _select_candidates(strategy, candidates)

    rounds = 1
    tie_breaker_selected: str | None = None
    tie_break_reason: str | None = None
    judge_name: str | None = None
    judge_score: float | None = None
    remaining = list(pool)
    max_rounds = config.max_rounds

    def _next_round() -> None:
        nonlocal rounds
        if max_rounds is not None and rounds >= max_rounds:
            raise ParallelExecutionError("consensus max_rounds exhausted")
        rounds += 1

    if config.tie_breaker is not None:
        tie_breakers: list[ConsensusTieBreaker] = [config.tie_breaker]
    else:
        tie_breakers = [
            ConsensusTieBreaker.MIN_LATENCY,
            ConsensusTieBreaker.MIN_COST,
            ConsensusTieBreaker.STABLE_ORDER,
        ]

    tie_break_applied = len(pool) > 1
    for breaker in tie_breakers:
        if len(remaining) <= 1:
            break
        _next_round()
        narrowed, reason = _apply_tie_breaker(breaker, remaining)
        tie_breaker_selected = breaker.value
        tie_break_reason = reason
        remaining = narrowed

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
    quorum = config.quorum if config.quorum is not None else 2
    if strategy is ConsensusStrategy.WEIGHTED_VOTE:
        votes_for_quorum = max(winner.weighted_votes, float(winner.votes))
    else:
        votes_for_quorum = float(winner.votes)
    if votes_for_quorum < float(quorum):
        raise ParallelExecutionError("consensus quorum not reached")

    return ConsensusResult(
        response=winner.primary,
        votes=winner.votes,
        tally=tally,
        total_voters=len(collected),
        strategy=strategy.value,
        min_votes=config.quorum,
        score_threshold=None,
        tie_breaker=(config.tie_breaker.value if config.tie_breaker else None),
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
    "ConsensusInput",
    "ConsensusResult",
    "invoke_consensus_judge",
    "validate_consensus_schema",
    "compute_consensus",
]
