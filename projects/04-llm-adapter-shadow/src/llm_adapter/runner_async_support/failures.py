"""Consensus failure aggregation helpers."""
from __future__ import annotations

from ..parallel_exec import ParallelExecutionError
from ..runner_async_modes import AsyncRunContext, collect_failure_details, WorkerResult


def emit_consensus_failure(
    *,
    context: AsyncRunContext,
    results: list[WorkerResult] | None,
    failure_details: list[dict[str, str]] | None,
    last_error: Exception | None,
) -> tuple[list[dict[str, str]] | None, Exception | None]:
    """Aggregate consensus failures and emit metrics/errors."""

    updated_details = failure_details
    if results is not None:
        for _, _, _, metrics in results:
            if metrics is not None:
                metrics.emit()
        no_success = not any(len(entry) >= 3 and entry[2] is not None for entry in results)
        if no_success and not updated_details:
            updated_details = collect_failure_details(context)
    elif not updated_details:
        updated_details = collect_failure_details(context)

    updated_error = last_error
    if updated_details and (
        updated_error is None or not isinstance(updated_error, ParallelExecutionError)
    ):
        detail_text = "; ".join(
            f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
            for item in updated_details
        )
        message = "all workers failed"
        if detail_text:
            message = f"{message}: {detail_text}"
        updated_error = ParallelExecutionError(message, failures=updated_details)

    return updated_details, updated_error


__all__ = ["emit_consensus_failure"]
