"""Consensus strategy for synchronous runner."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from .parallel_exec import ParallelAllResult, ParallelExecutionError
from .provider_spi import ProviderSPI, ProviderResponse
from .runner_parallel import compute_consensus
from .shadow import ShadowMetrics
from .utils import content_hash
from .runner_sync_modes import _limited_providers, _raise_no_attempts

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
        providers = _limited_providers(runner.providers, max_attempts)

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
            _raise_no_attempts(context)

        try:
            invocations = context.run_parallel_all(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            candidates: list[
                tuple[str, ProviderResponse, dict[str, object]]
            ] = []
            for invocation in invocations:
                response = invocation.response
                if response is None:
                    continue
                metadata: dict[str, object] = {
                    "invocation": invocation,
                    "attempt": invocation.attempt,
                    "latency_ms": response.latency_ms,
                    "tokens_in": invocation.tokens_in,
                    "tokens_out": invocation.tokens_out,
                }
                candidates.append(
                    (invocation.provider.name(), response, metadata)
                )
            if not candidates:
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
            responses_for_consensus = [response for _, response, _ in candidates]
            consensus = compute_consensus(
                responses_for_consensus,
                config=runner._config.consensus,
            )
            winner_name, _, winner_metadata = next(
                entry
                for entry in candidates
                if entry[1] is consensus.response
            )
            winner_invocation = cast(
                "ProviderInvocationResult",
                winner_metadata["invocation"],
            )
            votes_against = (
                consensus.total_voters - consensus.votes - consensus.abstained
            )
            event_logger = context.event_logger
            if event_logger is not None:
                candidate_summaries = [
                    {
                        "provider": provider_name,
                        "latency_ms": response.latency_ms,
                        "votes": consensus.tally.get(response.text.strip(), 0),
                        "text_hash": content_hash("consensus", response.text),
                    }
                    for provider_name, response, _ in candidates
                ]
                event_logger.emit(
                    "consensus_vote",
                    {
                        "request_fingerprint": context.request_fingerprint,
                        "strategy": consensus.strategy,
                        "tie_breaker": consensus.tie_breaker,
                        "min_votes": consensus.min_votes,
                        "score_threshold": consensus.score_threshold,
                        "voters_total": consensus.total_voters,
                        "votes_for": consensus.votes,
                        "votes_against": votes_against,
                        "abstained": consensus.abstained,
                        "winner_provider": winner_name,
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
