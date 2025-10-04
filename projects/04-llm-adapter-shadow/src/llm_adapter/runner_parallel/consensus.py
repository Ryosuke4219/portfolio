"""Consensus computation helpers for parallel runner."""
from __future__ import annotations

from collections.abc import Iterable

from ..consensus_candidates import (
    _apply_tie_breaker,
    _Candidate,
    _normalize_candidate_text,
    CandidateSet,
    validate_consensus_schema,
)
from ..parallel_exec import ParallelExecutionError
from ..provider_spi import ProviderResponse
from ..runner_config import ConsensusConfig
from .judge import invoke_consensus_judge
from .models import ConsensusObservation, ConsensusResult
from .observations import _normalize_observations


def compute_consensus(
    responses: Iterable[ProviderResponse | ConsensusObservation], *,
    config: ConsensusConfig | None = None,
) -> ConsensusResult:
    """Return the majority response according to ``config``."""

    collected = list(responses)
    if not collected:
        raise ValueError("responses must not be empty")
    if config is None:
        config = ConsensusConfig()
    strategy = (config.strategy or "majority").strip()
    tie_breaker = (config.tie_breaker or "").strip() or None

    observations = _normalize_observations(collected)
    provider_weights = {
        provider: float(weight)
        for provider, weight in (config.provider_weights or {}).items()
    }

    valid_entries, schema_failures, schema_checked = validate_consensus_schema(
        observations, config.schema
    )

    max_latency_ms = getattr(config, "max_latency_ms", None)
    max_cost_usd = getattr(config, "max_cost_usd", None)
    if max_latency_ms is not None or max_cost_usd is not None:
        filtered_entries: list[tuple[int, ConsensusObservation]] = []
        constraint_failures: list[dict[str, str]] = []
        for index, entry in valid_entries:
            reasons: list[str] = []
            latency = entry.latency_ms
            if (
                max_latency_ms is not None
                and latency is not None
                and latency > max_latency_ms
            ):
                reasons.append(
                    f"latency {latency}ms exceeds max {max_latency_ms}ms"
                )
            cost = entry.cost_estimate
            if (
                max_cost_usd is not None
                and cost is not None
                and cost > max_cost_usd
            ):
                reasons.append(
                    f"cost {cost} exceeds max {max_cost_usd}"
                )
            if reasons:
                detail: dict[str, str] = {
                    "provider": entry.provider_id,
                    "summary": "; ".join(reasons),
                }
                detail["index"] = str(index)
                if latency is not None:
                    detail["latency_ms"] = str(latency)
                if cost is not None:
                    detail["cost_usd"] = str(cost)
                constraint_failures.append(detail)
                continue
            filtered_entries.append((index, entry))
        valid_entries = filtered_entries
        if not valid_entries:
            raise ParallelExecutionError(
                "no responses satisfied consensus constraints",
                failures=constraint_failures or None,
            )

    if not valid_entries:
        raise ParallelExecutionError("all responses failed schema validation")

    candidate_set = CandidateSet.from_observations(valid_entries, provider_weights)
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

    if tie_break_applied:
        if tie_breaker is not None:
            _next_round()
            remaining, tie_break_reason, tie_breaker_selected = _apply_tie_breaker(
                tie_breaker, remaining
            )
        else:
            _next_round()
            for fallback in ("min_latency", "min_cost", "stable_order"):
                if len(remaining) <= 1:
                    break
                narrowed, reason, selected = _apply_tie_breaker(fallback, remaining)
                if len(narrowed) < len(remaining):
                    remaining = narrowed
                    tie_break_reason = reason
                    tie_breaker_selected = selected
                    break
            else:  # pragma: no cover - defensive guard
                remaining, tie_break_reason, tie_breaker_selected = remaining, None, None

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

    total_valid_voters = len(valid_entries)
    quorum_required = config.quorum if config.quorum is not None else total_valid_voters

    reason_parts = [strategy]
    reason_parts.append(f"quorum={quorum_required}/{total_valid_voters}")
    if tie_break_applied:
        tie_detail = tie_breaker_selected or tie_breaker or "tie"
        reason_parts.append(f"tie_breaker={tie_detail}")
        if tie_break_reason:
            reason_parts.append(f"tie_break_reason={tie_break_reason}")
    if judge_name:
        reason_parts.append(f"judge={judge_name}")
        if judge_score is not None:
            reason_parts.append(f"judge_score={judge_score:g}")

    reason = " ".join(reason_parts)

    return ConsensusResult(
        response=winner.primary,
        votes=votes,
        tally=tally,
        total_voters=len(observations),
        reason=reason,
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
    "ConsensusObservation",
    "ConsensusResult",
    "compute_consensus",
    "invoke_consensus_judge",
    "_Candidate",
    "_normalize_candidate_text",
    "validate_consensus_schema",
]
