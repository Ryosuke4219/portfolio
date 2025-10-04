"""Event logging helpers shared across runners."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..errors import FatalError, ProviderSkip, RateLimitError, RetryableError, SkipError
from ..observability import EventLogger, JsonlLogger
from ..utils import content_hash
from .costs import estimate_cost, provider_model

if TYPE_CHECKING:
    from ..provider_spi import AsyncProviderSPI, ProviderRequest, ProviderSPI

MetricsPath = str | Path | None


def resolve_event_logger(
    logger: EventLogger | None,
    metrics_path: MetricsPath,
) -> tuple[EventLogger | None, str | None]:
    """Resolve the event logger and materialized metrics path."""
    metrics_path_str = None if metrics_path is None else str(Path(metrics_path))
    if metrics_path_str is None:
        return None, None
    if logger is not None:
        return logger, metrics_path_str
    return JsonlLogger(metrics_path_str), metrics_path_str


def error_family(error: Exception | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, RateLimitError):
        return "rate_limit"
    if isinstance(error, SkipError):
        return "skip"
    if isinstance(error, FatalError):
        return "fatal"
    if isinstance(error, RetryableError):
        return "retryable"
    return "unknown"


def _provider_name(provider: ProviderSPI | AsyncProviderSPI | None) -> str | None:
    if provider is None:
        return None
    if hasattr(provider, "name"):
        name = provider.name  # type: ignore[attr-defined]
        if callable(name):
            return str(name())
    return None


def _request_hash(
    provider_name: str | None, request: ProviderRequest
) -> str | None:
    if provider_name is None:
        return None
    return content_hash(
        provider_name,
        request.prompt_text,
        request.options,
        request.max_tokens,
    )


def log_provider_skipped(
    event_logger: EventLogger | None,
    *,
    request_fingerprint: str,
    provider: ProviderSPI | AsyncProviderSPI,
    request: ProviderRequest,
    attempt: int,
    total_providers: int,
    error: SkipError,
) -> None:
    if event_logger is None:
        return
    provider_name = _provider_name(provider)
    event_logger.emit(
        "provider_skipped",
        {
            "request_fingerprint": request_fingerprint,
            "request_hash": _request_hash(provider_name, request),
            "provider": provider_name,
            "attempt": attempt,
            "total_providers": total_providers,
            "reason": error.reason if isinstance(error, ProviderSkip) else None,
            "error_message": str(error),
        },
    )


def _normalize_outcome(status: str) -> str:
    normalized = status.lower()
    success_values = {"ok", "success"}
    error_values = {"error", "errored", "failure"}
    skipped_values = {"skip", "skipped"}
    if normalized in success_values:
        return "success"
    if normalized in error_values:
        return "error"
    if normalized in skipped_values:
        return "skipped"
    return normalized


def _extract_shadow_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    direct_latency = metadata.get("shadow_latency_ms")
    direct_duration = metadata.get("shadow_duration_ms")
    direct_outcome = metadata.get("shadow_outcome")

    if direct_latency is not None:
        result["shadow_latency_ms"] = direct_latency
    if direct_duration is not None:
        result["shadow_duration_ms"] = direct_duration
    if direct_outcome is not None:
        result["shadow_outcome"] = direct_outcome

    shadow_metadata = metadata.get("shadow")
    if isinstance(shadow_metadata, Mapping):
        latency = shadow_metadata.get("latency_ms")
        duration = shadow_metadata.get("duration_ms")
        outcome = shadow_metadata.get("outcome")

        if "shadow_latency_ms" not in result and latency is not None:
            result["shadow_latency_ms"] = latency
        if "shadow_duration_ms" not in result and duration is not None:
            result["shadow_duration_ms"] = duration
        if "shadow_outcome" not in result and outcome is not None:
            result["shadow_outcome"] = outcome

    return result


def log_provider_call(
    event_logger: EventLogger | None,
    *,
    request_fingerprint: str,
    provider: ProviderSPI | AsyncProviderSPI,
    request: ProviderRequest,
    attempt: int,
    total_providers: int,
    status: str,
    latency_ms: int | None,
    tokens_in: int | None,
    tokens_out: int | None,
    error: Exception | None,
    metadata: Mapping[str, Any],
    shadow_used: bool,
    allow_private_model: bool = False,
) -> None:
    if event_logger is None:
        return

    provider_name = _provider_name(provider)
    prompt_tokens = int(tokens_in) if tokens_in is not None else 0
    completion_tokens = int(tokens_out) if tokens_out is not None else 0
    if tokens_in is None or tokens_out is None:
        cost_estimate = 0.0
    else:
        cost_estimate = estimate_cost(provider, prompt_tokens, completion_tokens)
    token_usage = {
        "prompt": prompt_tokens,
        "completion": completion_tokens,
        "total": prompt_tokens + completion_tokens,
    }
    retries = max(0, attempt - 1)
    shadow_metadata = _extract_shadow_metadata(metadata)

    event_logger.emit(
        "provider_call",
        {
            "request_fingerprint": request_fingerprint,
            "run_id": request_fingerprint,
            "request_hash": _request_hash(provider_name, request),
            "provider": provider_name,
            "provider_id": provider_name,
            "model": provider_model(provider, allow_private=allow_private_model),
            "attempt": attempt,
            "retries": retries,
            "total_providers": total_providers,
            "status": status,
            "outcome": _normalize_outcome(status),
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "token_usage": token_usage,
            "cost_estimate": cost_estimate,
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "error_family": error_family(error),
            "shadow_used": shadow_used,
            "shadow_provider_id": metadata.get("shadow_provider_id"),
            "shadow_latency_ms": metadata.get("shadow_latency_ms"),
            "shadow_outcome": metadata.get("shadow_outcome"),
            "mode": metadata.get("mode"),
            "providers": metadata.get("providers"),
            "trace_id": metadata.get("trace_id"),
            "project_id": metadata.get("project_id"),
            **shadow_metadata,
        },
    )


def log_run_metric(
    event_logger: EventLogger | None,
    *,
    request_fingerprint: str,
    request: ProviderRequest,
    provider: ProviderSPI | AsyncProviderSPI | None,
    status: str,
    attempts: int,
    latency_ms: int,
    tokens_in: int | None,
    tokens_out: int | None,
    cost_usd: float,
    error: Exception | None,
    metadata: Mapping[str, Any],
    shadow_used: bool,
) -> None:
    if event_logger is None:
        return

    provider_name = _provider_name(provider)
    mode = metadata.get("mode")
    providers = metadata.get("providers")
    shadow_provider_id = metadata.get("shadow_provider_id")
    retries = attempts - 1 if attempts > 0 else 0
    outcome = _normalize_outcome(status)
    cost_estimate = float(cost_usd)
    prompt_tokens = tokens_in if tokens_in is not None else 0
    completion_tokens = tokens_out if tokens_out is not None else 0
    token_usage = {
        "prompt": prompt_tokens,
        "completion": completion_tokens,
        "total": prompt_tokens + completion_tokens,
    }
    shadow_metadata = _extract_shadow_metadata(metadata)

    event_logger.emit(
        "run_metric",
        {
            "request_fingerprint": request_fingerprint,
            "run_id": request_fingerprint,
            "request_hash": _request_hash(provider_name, request),
            "provider": provider_name,
            "provider_id": provider_name,
            "status": status,
            "outcome": outcome,
            "attempts": attempts,
            "retries": retries,
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "token_usage": token_usage,
            "cost_usd": cost_estimate,
            "cost_estimate": cost_estimate,
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "error_family": error_family(error),
            "shadow_used": shadow_used,
            "shadow_provider_id": shadow_provider_id,
            "shadow_latency_ms": metadata.get("shadow_latency_ms"),
            "shadow_outcome": metadata.get("shadow_outcome"),
            "mode": mode,
            "providers": providers,
            "trace_id": metadata.get("trace_id"),
            "project_id": metadata.get("project_id"),
            **shadow_metadata,
        },
    )


__all__ = [
    "MetricsPath",
    "resolve_event_logger",
    "error_family",
    "log_provider_skipped",
    "log_provider_call",
    "log_run_metric",
]
