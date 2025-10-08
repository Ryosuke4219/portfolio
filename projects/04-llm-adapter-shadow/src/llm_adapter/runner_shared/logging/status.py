"""Status normalization helpers."""

from collections.abc import Mapping
from typing import Any

from ...errors import FatalError, RateLimitError, RetryableError, SkipError


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


def _normalize_outcome(status: str) -> str:
    normalized = status.lower()
    success_values = {"ok", "success"}
    error_values = {"error", "errored", "failure", "fail", "failed"}
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


__all__ = [
    "error_family",
    "_normalize_outcome",
    "_extract_shadow_metadata",
]
