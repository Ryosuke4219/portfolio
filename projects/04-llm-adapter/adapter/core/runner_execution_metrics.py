"""Metrics helpers for :mod:`adapter.core.runner_execution`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .metrics.costs import estimate_cost
from .metrics.models import RunMetrics
from .metrics.update import finalize_run_metrics

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from collections.abc import Sequence

    from ._provider_execution import _ProviderCallResult
    from .config import ProviderConfig
    from .datasets import GoldenTask
    from .execution.guards import _SchemaValidator
    from .execution.shadow_runner import ShadowRunnerResult
    from .providers import ProviderResponse
    from .runner_execution import _BuildMetrics, _EvaluateBudget


@dataclass(slots=True)
class SingleRunResult:
    metrics: RunMetrics
    raw_output: str
    stop_reason: str | None = None
    aggregate_output: str | None = None
    error: Exception | None = None
    backoff_next_provider: bool = False


def apply_schema_validation(
    validator: _SchemaValidator | None,
    response: ProviderResponse,
    status: str,
    failure_kind: str | None,
    error_message: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    """Apply optional schema validation to a provider response."""

    schema_error: str | None = None
    if validator is not None:
        try:
            validator.validate(response.output_text or "")
        except ValueError as exc:
            schema_error = str(exc)
    if schema_error:
        if status == "ok":
            status = "error"
        failure_kind = failure_kind or "schema_violation"
        error_message = f"{error_message} | {schema_error}" if error_message else schema_error
    return status, failure_kind, error_message, schema_error


def build_single_run_result(
    *,
    provider_config: ProviderConfig,
    task: GoldenTask,
    attempt_index: int,
    mode: str,
    provider_result: _ProviderCallResult,
    evaluate_budget: _EvaluateBudget,
    build_metrics: _BuildMetrics,
    schema_validator: _SchemaValidator | None,
    shadow_result: ShadowRunnerResult | None,
    fallback_shadow_id: str | None,
    active_provider_ids: Sequence[str],
    current_attempt_index: int,
) -> SingleRunResult:
    """Finalize metrics for a single provider run."""

    response = provider_result.response
    status = provider_result.status
    failure_kind = provider_result.failure_kind
    error_message = provider_result.error_message
    cost_usd = estimate_cost(provider_config, response.input_tokens, response.output_tokens)
    budget_snapshot, stop_reason, status, failure_kind, error_message = evaluate_budget(
        provider_config,
        cost_usd,
        status,
        failure_kind,
        error_message,
    )
    status, failure_kind, error_message, schema_error = apply_schema_validation(
        schema_validator,
        response,
        status,
        failure_kind,
        error_message,
    )
    run_metrics, raw_output = build_metrics(
        provider_config,
        task,
        attempt_index,
        mode,
        response,
        status,
        failure_kind,
        error_message,
        provider_result.latency_ms,
        budget_snapshot,
        cost_usd,
    )
    finalize_run_metrics(
        run_metrics,
        attempt_index=attempt_index,
        provider_result=provider_result,
        response=response,
        status=status,
        failure_kind=failure_kind,
        error_message=error_message,
        schema_error=schema_error,
        shadow_result=shadow_result,
        fallback_shadow_id=fallback_shadow_id,
        active_provider_ids=active_provider_ids,
        current_attempt_index=current_attempt_index,
    )
    return SingleRunResult(
        metrics=run_metrics,
        raw_output=raw_output,
        stop_reason=stop_reason,
        error=provider_result.error,
        backoff_next_provider=provider_result.backoff_next_provider,
    )


__all__ = [
    "SingleRunResult",
    "apply_schema_validation",
    "build_single_run_result",
]
