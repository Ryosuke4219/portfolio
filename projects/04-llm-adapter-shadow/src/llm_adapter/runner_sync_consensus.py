"""Consensus strategy for synchronous runner."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from .parallel_exec import ParallelAllResult, ParallelExecutionError
from .provider_spi import ProviderSPI, ProviderResponse
from .runner_parallel import ConsensusInput, compute_consensus
from .shadow import ShadowMetrics
from .utils import content_hash
from . import runner_sync_modes

if TYPE_CHECKING:
    from .runner_sync import ProviderInvocationResult
    from .runner_sync_modes import SyncRunContext


class ConsensusStrategy:
    def execute(
        self, context: "SyncRunContext"
    ) -> ProviderResponse | ParallelAllResult[
        "ProviderInvocationResult", ProviderResponse
    ]:
        runner = context.runner
        total_providers = len(runner.providers)
        results: list["ProviderInvocationResult" | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = runner_sync_modes._limited_providers(
            runner.providers, max_attempts
        )

        def make_worker(
            index: int, provider: ProviderSPI
        ) -> Callable[[], "ProviderInvocationResult"]:
            def worker() -> "ProviderInvocationResult":
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=True,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            runner_sync_modes._raise_no_attempts(context)

        try:
            invocations = context.run_parallel_all(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            successful: list[tuple["ProviderInvocationResult", ProviderResponse]] = [
                (res, res.response)
                for res in invocations
                if res.response is not None
            ]
            if not successful:
                failure_details: list[dict[str, str]] = []
                for invocation in invocations:
                    provider_name = invocation.provider.name()
                    attempt_label = str(invocation.attempt)
                    error = invocation.error
                    summary = (
                        f"{type(error).__name__}: {error}"
                        if error is not None
                        else "unknown error"
                    )
                    failure_details.append(
                        {
                            "provider": provider_name,
                            "attempt": attempt_label,
                            "summary": summary,
                        }
                    )
                detail_text = "; ".join(
                    f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
                    for item in failure_details
                )
                message = "all workers failed"
                if detail_text:
                    message = f"{message}: {detail_text}"
                error = ParallelExecutionError(message, failures=failure_details)
                raise error
            consensus_inputs = [
                ConsensusInput(
                    provider=invocation.provider,
                    response=response,
                    order=index,
                )
                for index, (invocation, response) in enumerate(successful)
            ]
            consensus = compute_consensus(
                consensus_inputs,
                config=runner._config.consensus,
            )
            winner_invocation = next(
                invocation
                for invocation, response in successful
                if response is consensus.response
            )
            votes_against = (
                consensus.total_voters - consensus.votes - consensus.abstained
            )
            event_logger = context.event_logger
            strategy_value = getattr(consensus.strategy, "value", consensus.strategy)
            tie_breaker_value = (
                getattr(consensus.tie_breaker, "value", consensus.tie_breaker)
                if consensus.tie_breaker is not None
                else None
            )
            if event_logger is not None:
                candidate_summaries = [
                    {
                        "provider": invocation.provider.name(),
                        "latency_ms": response.latency_ms,
                        "votes": consensus.tally.get(response.text.strip(), 0),
                        "text_hash": content_hash("consensus", response.text),
                    }
                    for invocation, response in successful
                ]
                event_logger.emit(
                    "consensus_vote",
                    {
                        "request_fingerprint": context.request_fingerprint,
                        "strategy": strategy_value,
                        "tie_breaker": tie_breaker_value,
                        "min_votes": consensus.min_votes,
                        "score_threshold": consensus.score_threshold,
                        "voters_total": consensus.total_voters,
                        "votes_for": consensus.votes,
                        "votes_against": votes_against,
                        "abstained": consensus.abstained,
                        "winner_provider": winner_invocation.provider.name(),
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
            if winner_invocation.shadow_metrics is not None:
                shadow_metrics = cast(ShadowMetrics, winner_invocation.shadow_metrics)
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
                    }
                }
                if not shadow_payload.get("shadow_ok", True):
                    error = shadow_payload.get("shadow_error")
                    if error is not None:
                        extra["shadow_consensus_error"] = error
                winner_invocation.shadow_metrics_extra = extra
            return consensus.response
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            raise exc
        finally:
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
            )
