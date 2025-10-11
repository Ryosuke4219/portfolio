from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
from typing import TYPE_CHECKING

from .provider_spi import ProviderResponse

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .runner_parallel.models import ConsensusObservation


@dataclass(slots=True)
class _Candidate:
    normalized: str
    text: str
    raw_text: str
    entries: list[tuple[int, ConsensusObservation]] = field(default_factory=list)
    votes: int = 0
    score: float = 0.0
    best_score: float = 0.0
    latency: int = 0
    cost: float = 0.0
    weight: float = 0.0
    stable_index: int = 0

    def record(
        self,
        index: int,
        observation: ConsensusObservation,
        weight: float,
    ) -> None:
        response = observation.response
        if response is None:
            return
        self.entries.append((index, observation))
        self.votes += 1
        self.weight = weight if self.votes == 1 else self.weight + weight
        value = _extract_score(response)
        self.score += value
        self.best_score = value if self.votes == 1 else max(self.best_score, value)
        latency = _resolve_latency(observation, response)
        cost = _resolve_cost(observation, response)
        self.latency = latency if self.votes == 1 else min(self.latency, latency)
        self.cost = cost if self.votes == 1 else min(self.cost, cost)
        self.stable_index = index if self.votes == 1 else min(self.stable_index, index)

    @property
    def primary(self) -> ProviderResponse:
        return min(self.entries, key=lambda item: item[0])[1].response  # type: ignore[return-value]


class CandidateSet:
    def __init__(self, candidates: dict[str, _Candidate]) -> None:
        self._candidates = candidates

    @classmethod
    def from_observations(
        cls,
        entries: Iterable[tuple[int, ConsensusObservation]],
        provider_weights: Mapping[str, float] | None,
    ) -> CandidateSet:
        candidates: dict[str, _Candidate] = {}
        weights = provider_weights or {}
        for index, observation in entries:
            response = observation.response
            if response is None:
                continue
            normalized, display_text = _normalize_candidate_text(response.text)
            candidate = candidates.get(normalized)
            if candidate is None:
                candidate = _Candidate(
                    normalized=normalized,
                    text=display_text,
                    raw_text=response.text,
                )
                candidates[normalized] = candidate
            weight = float(weights.get(observation.provider_id, 1.0))
            candidate.record(index, observation, weight)
        return cls(candidates)

    def is_empty(self) -> bool:
        return not self._candidates

    def tally(self) -> dict[str, int]:
        return {candidate.text: candidate.votes for candidate in self._candidates.values()}

    def select(self, strategy: str) -> tuple[list[_Candidate], float, dict[str, float] | None]:
        return _select_candidates(strategy, self._candidates)

    def values(self) -> Sequence[_Candidate]:
        return tuple(self._candidates.values())


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


def _select_candidates(
    strategy: str, candidates: Mapping[str, _Candidate]
) -> tuple[list[_Candidate], float, dict[str, float] | None]:
    normalized = strategy.strip().lower().replace("-", "_")
    values = list(candidates.values())
    if normalized in {"majority", "majority_vote"}:
        pivot_votes = max(candidate.votes for candidate in values)
        pool = [candidate for candidate in values if candidate.votes == pivot_votes]
        return pool, float(pivot_votes), None
    if normalized in {"weighted", "weighted_score"}:
        scores = {candidate.text: candidate.score for candidate in values}
        pivot_score = max(scores.values())
        pool = [
            candidate
            for candidate in values
            if math.isclose(candidate.score, pivot_score, rel_tol=1e-9, abs_tol=1e-9)
        ]
        return pool, float(pivot_score), scores
    if normalized == "max_score":
        scores = {candidate.text: candidate.best_score for candidate in values}
        pivot_score = max(scores.values())
        pool = [
            candidate
            for candidate in values
            if math.isclose(candidate.best_score, pivot_score, rel_tol=1e-9, abs_tol=1e-9)
        ]
        return pool, float(pivot_score), scores
    if normalized == "weighted_vote":
        weights = {candidate.text: candidate.weight for candidate in values}
        pivot_weight = max(weights.values())
        pool = [
            candidate
            for candidate in values
            if math.isclose(candidate.weight, pivot_weight, rel_tol=1e-9, abs_tol=1e-9)
        ]
        return pool, float(pivot_weight), weights
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
    chosen = min(candidates, key=lambda candidate: (candidate.normalized, candidate.stable_index))
    return [chosen], f"stable_order(text={chosen.text})"


def _apply_tie_breaker(
    name: str, candidates: Sequence[_Candidate]
) -> tuple[list[_Candidate], str, str]:
    normalized = name.strip().lower().replace("-", "_")
    handlers: dict[str, Callable[[Sequence[_Candidate]], tuple[list[_Candidate], str]]] = {
        "latency": _tie_break_by_latency,
        "cost": _tie_break_by_cost,
        "stable_order": _tie_break_by_stable_order,
    }
    alias = {
        "min_latency": "latency",
        "min_cost": "cost",
        "stable_order": "stable_order",
        "latency": "latency",
        "cost": "cost",
    }
    handler = handlers.get(alias.get(normalized, ""))
    if handler is None:
        raise ValueError(f"unknown tie_breaker: {name!r}")
    narrowed, reason = handler(candidates)
    if normalized == "min_latency":
        reason = reason.replace("latency", "min_latency", 1)
    elif normalized == "min_cost":
        reason = reason.replace("cost", "min_cost", 1)
    return narrowed, reason, normalized


def validate_consensus_schema(
    responses: Sequence[ConsensusObservation], schema: str | None
) -> tuple[list[tuple[int, ConsensusObservation]], dict[int, str], bool]:
    if not schema:
        return list(enumerate(responses)), {}, False

    try:
        schema_spec = json.loads(schema)
    except json.JSONDecodeError as exc:  # pragma: no cover - config error
        raise ValueError("invalid consensus schema") from exc
    if not isinstance(schema_spec, Mapping):
        raise ValueError("invalid consensus schema")

    valid_entries: list[tuple[int, ConsensusObservation]] = []
    failures: dict[int, str] = {}
    expected_type = schema_spec.get("type")
    required_fields = [str(field) for field in schema_spec.get("required", [])]

    for index, observation in enumerate(responses):
        response = observation.response
        if response is None:
            continue
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
        valid_entries.append((index, observation))

    return valid_entries, failures, True


def _resolve_latency(
    observation: ConsensusObservation, response: ProviderResponse
) -> int:
    if observation.latency_ms is not None:
        return int(observation.latency_ms)
    return int(response.latency_ms)


def _resolve_cost(
    observation: ConsensusObservation, response: ProviderResponse
) -> float:
    if observation.cost_estimate is not None:
        return float(observation.cost_estimate)
    tokens = observation.tokens or response.token_usage
    if tokens is not None:
        return float((tokens.prompt or 0) + (tokens.completion or 0))
    return float((response.tokens_in or 0) + (response.tokens_out or 0))


__all__ = [
    "CandidateSet",
    "_Candidate",
    "_normalize_candidate_text",
    "_apply_tie_breaker",
    "validate_consensus_schema",
]

