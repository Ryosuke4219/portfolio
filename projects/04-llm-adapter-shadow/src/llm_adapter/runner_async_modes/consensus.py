"""Consensus run strategy."""
from __future__ import annotations

from ..parallel_exec import ParallelExecutionError, run_parallel_all_async
from ..runner_parallel import compute_consensus, ConsensusObservation
from ..runner_shared import estimate_cost, log_run_metric
from ..utils import content_hash, elapsed_ms
from .base import ParallelStrategyBase
from .context import AsyncRunContext, collect_failure_details, StrategyResult


class ConsensusRunStrategy(ParallelStrategyBase):
    def __init__(self) -> None:
        super().__init__(capture_shadow_metrics=True, is_parallel_any=False)

    async def run(self, context: AsyncRunContext) -> StrategyResult:
        self._reset_context(context)
        workers = self._create_workers(context)
        try:
            results = await run_parallel_all_async(
                workers,
                max_concurrency=context.config.max_concurrency,
                max_attempts=context.config.max_attempts,
                on_retry=lambda index, attempt, error: self._on_retry(
                    context, index, attempt, error
                ),
            )
        except Exception as err:  # noqa: BLE001
            context.last_error = err
            return StrategyResult(None, context.attempt_count, context.last_error)

        context.results = results
        successful_entries = [
            entry for entry in results if len(entry) >= 3 and entry[2] is not None
        ]
        if not successful_entries:
            failure_details = collect_failure_details(context)
            detail_text = "; ".join(
                f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
                for item in failure_details
            )
            message = "all workers failed"
            if detail_text:
                message = f"{message}: {detail_text}"
            context.last_error = ParallelExecutionError(
                message, failures=failure_details or None
            )
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                results=results,
                failure_details=failure_details,
            )

        try:
            observations: list[ConsensusObservation] = []
            for _attempt, provider, response, _ in successful_entries:
                provider_name: str
                name_attr = getattr(provider, "name", None)
                if callable(name_attr):
                    provider_name = str(name_attr())
                else:
                    provider_name = type(provider).__name__
                tokens = response.token_usage
                tokens_in = int(tokens.prompt or 0) if tokens is not None else 0
                tokens_out = int(tokens.completion or 0) if tokens is not None else 0
                observations.append(
                    ConsensusObservation(
                        provider_id=provider_name,
                        response=response,
                        latency_ms=int(response.latency_ms or 0),
                        tokens=tokens,
                        cost_estimate=estimate_cost(provider, tokens_in, tokens_out),
                    )
                )
            consensus = compute_consensus(
                observations,
                config=context.config.consensus,
            )
        except ParallelExecutionError as err:
            context.last_error = err
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                results=results,
            )

        try:
            winner_entry = next(
                (
                    attempt,
                    provider,
                    response,
                    metrics,
                )
                for attempt, provider, response, metrics in successful_entries
                if response is consensus.response
            )
        except StopIteration:
            context.last_error = ParallelExecutionError("consensus resolution failed")
            return StrategyResult(
                None,
                context.attempt_count,
                context.last_error,
                results=results,
            )
        attempt_index, provider, response, shadow_metrics = winner_entry
        votes_against = consensus.total_voters - consensus.votes - consensus.abstained
        if context.event_logger is not None:
            candidate_summaries = [
                {
                    "provider": prov.name(),
                    "latency_ms": resp.latency_ms,
                    "votes": consensus.tally.get(resp.text.strip(), 0),
                    "text_hash": content_hash("consensus", resp.text),
                }
                for _attempt, prov, resp, _ in successful_entries
            ]
            context.event_logger.emit(
                "consensus_vote",
                {
                    "request_fingerprint": context.request_fingerprint,
                    "reason": consensus.reason,
                    "strategy": consensus.strategy,
                    "tie_breaker": consensus.tie_breaker,
                    "quorum": consensus.min_votes,
                    "min_votes": consensus.min_votes,
                    "score_threshold": consensus.score_threshold,
                    "voters_total": consensus.total_voters,
                    "votes_for": consensus.votes,
                    "votes_against": votes_against,
                    "abstained": consensus.abstained,
                    "chosen_provider": provider.name(),
                    "winner_provider": provider.name(),
                    "winner_score": consensus.winner_score,
                    "winner_latency_ms": consensus.response.latency_ms,
                    "tie_break_applied": consensus.tie_break_applied,
                    "tie_break_reason": consensus.tie_break_reason,
                    "tie_breaker_selected": consensus.tie_breaker_selected,
                    "rounds": consensus.rounds,
                    "scores": consensus.scores,
                    "schema_checked": consensus.schema_checked,
                    "schema_failures": consensus.schema_failures,
                    "judge": consensus.judge_name,
                    "judge_score": consensus.judge_score,
                    "votes": dict(consensus.tally),
                    "candidate_summaries": candidate_summaries,
                },
            )
        usage = response.token_usage
        tokens_in = usage.prompt
        tokens_out = usage.completion
        cost_usd = estimate_cost(provider, tokens_in, tokens_out)
        log_run_metric(
            context.event_logger,
            request_fingerprint=context.request_fingerprint,
            request=context.request,
            provider=provider,
            status="ok",
            attempts=context.attempt_count,
            latency_ms=elapsed_ms(context.run_started),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            error=None,
            metadata=context.metadata,
            shadow_used=context.shadow is not None,
        )
        if shadow_metrics is not None:
            shadow_payload = shadow_metrics.payload
            extra: dict[str, object] = {
                "shadow_consensus_delta": {
                    "votes_for": consensus.votes,
                    "votes_total": consensus.total_voters,
                    "tie_break_applied": consensus.tie_break_applied,
                    "winner_score": consensus.winner_score,
                    "rounds": consensus.rounds,
                    "tie_break_reason": consensus.tie_break_reason,
                    "tie_breaker_selected": consensus.tie_breaker_selected,
                    "judge": consensus.judge_name,
                    "judge_score": consensus.judge_score,
                    "reason": consensus.reason,
                }
            }
            if not shadow_payload.get("shadow_ok", True):
                error = shadow_payload.get("shadow_error")
                if error is not None:
                    extra["shadow_consensus_error"] = error
            shadow_metrics.emit(extra)
        for _, _, _, metrics in results:
            if metrics is not None and metrics is not shadow_metrics:
                metrics.emit()
        return StrategyResult(response, context.attempt_count, None, results=results)
