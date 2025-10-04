"""実行メトリクスの更新ロジック。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol, TYPE_CHECKING

from .models import RunMetrics


class ProviderCallResult(Protocol):
    error: Exception | None
    retries: int


def finalize_run_metrics(
    run_metrics: RunMetrics,
    *,
    attempt_index: int,
    provider_result: ProviderCallResult,
    response: ProviderResponse,
    status: str,
    failure_kind: str | None,
    error_message: str | None,
    schema_error: str | None,
    shadow_result: ShadowRunnerResult | None,
    fallback_shadow_id: str | None,
    active_provider_ids: Sequence[str],
    current_attempt_index: int,
) -> None:
    provider_ids: list[str] = []
    for provider_id in active_provider_ids:
        if provider_id not in provider_ids:
            provider_ids.append(provider_id)
    run_metrics.providers = provider_ids

    usage = response.token_usage
    prompt_tokens = int(getattr(usage, "prompt", response.input_tokens))
    completion_tokens = int(getattr(usage, "completion", response.output_tokens))
    total_tokens = int(getattr(usage, "total", prompt_tokens + completion_tokens))
    run_metrics.token_usage = {
        "prompt": prompt_tokens,
        "completion": completion_tokens,
        "total": total_tokens,
    }

    run_metrics.attempts = attempt_index + 1
    run_metrics.error_type = (
        type(provider_result.error).__name__ if provider_result.error else None
    )
    run_metrics.retries = max(current_attempt_index, 0) + max(provider_result.retries - 1, 0)

    if schema_error:
        run_metrics.status = status
        run_metrics.failure_kind = failure_kind
        run_metrics.error_message = error_message

    run_metrics.outcome = _resolve_outcome(run_metrics.status)
    apply_shadow_metrics(run_metrics, shadow_result, fallback_shadow_id)


def apply_shadow_metrics(
    run_metrics: RunMetrics,
    shadow_result: ShadowRunnerResult | None,
    fallback_shadow_id: str | None,
) -> None:
    if shadow_result is None:
        if fallback_shadow_id is not None:
            run_metrics.shadow_provider_id = fallback_shadow_id
        return

    provider_id = shadow_result.provider_id or fallback_shadow_id
    if provider_id is not None:
        run_metrics.shadow_provider_id = provider_id
    if shadow_result.latency_ms is not None:
        run_metrics.shadow_latency_ms = int(shadow_result.latency_ms)
    if shadow_result.status is not None:
        run_metrics.shadow_status = shadow_result.status
        run_metrics.shadow_outcome = _resolve_outcome(shadow_result.status)
    if shadow_result.error_message is not None:
        run_metrics.shadow_error_message = shadow_result.error_message


def _resolve_outcome(status: str) -> Literal["success", "skip", "error"]:
    if status == "ok":
        return "success"
    if status == "skip":
        return "skip"
    return "error"


if TYPE_CHECKING:  # pragma: no cover - 循環参照の回避
    from ..execution.shadow_runner import ShadowRunnerResult
    from ..providers import ProviderResponse
