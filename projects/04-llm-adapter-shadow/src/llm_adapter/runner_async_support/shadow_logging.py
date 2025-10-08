"""Shadow logging helpers for :mod:`llm_adapter.runner_async`."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..shadow import ShadowMetrics


def build_shadow_log_metadata(shadow_metrics: ShadowMetrics | None) -> dict[str, Any]:
    """Build logging metadata derived from shadow execution metrics."""

    if shadow_metrics is None:
        return {}
    payload: Mapping[str, Any] = shadow_metrics.payload
    metadata: dict[str, Any] = {}
    latency = payload.get("shadow_latency_ms")
    if isinstance(latency, int | float):
        metadata["shadow_latency_ms"] = int(latency)
    outcome_value: Any = payload.get("shadow_outcome")
    mapped_outcome: str | None = None
    if isinstance(outcome_value, str):
        normalized = outcome_value.lower()
        if normalized in {"success", "error", "timeout"}:
            mapped_outcome = normalized
        else:
            mapped_outcome = outcome_value
    elif payload.get("shadow_ok") is True:
        mapped_outcome = "success"
    elif payload.get("shadow_ok") is False:
        mapped_outcome = "error"
    if mapped_outcome is not None:
        metadata["shadow_outcome"] = mapped_outcome
    return metadata


__all__ = ["build_shadow_log_metadata"]
