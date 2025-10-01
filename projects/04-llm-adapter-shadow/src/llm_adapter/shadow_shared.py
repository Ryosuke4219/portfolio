from __future__ import annotations

from typing import Any

from .observability import EventLogger
from .provider_spi import ProviderRequest, ProviderResponse
from .shadow_metrics import _build_shadow_record, _emit_shadow_metrics, ShadowMetrics

DEFAULT_METRICS_PATH = "artifacts/runs-metrics.jsonl"


def _make_shadow_payload(
    *,
    provider_name: str | None,
    response: ProviderResponse | None = None,
    error: Exception | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"provider": provider_name}
    if response is not None:
        payload.update(
            {
                "ok": True,
                "latency_ms": response.latency_ms,
                "text_len": len(response.text),
                "token_usage_total": response.token_usage.total,
                "outcome": "success",
            }
        )
    else:
        payload.update({"ok": False, "outcome": "error"})
        if error is not None:
            payload["error"] = type(error).__name__
            payload["message"] = str(error)
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return payload


def _make_timeout_payload(
    provider_name: str | None, duration_ms: int | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider_name,
        "ok": False,
        "error": "ShadowTimeout",
        "outcome": "timeout",
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return payload


def _finalize_shadow_metrics(
    *,
    metrics_path: str | None,
    capture_metrics: bool,
    logger: EventLogger | None,
    primary_provider_name: str,
    primary_response: ProviderResponse,
    request: ProviderRequest,
    shadow_payload: dict[str, Any] | None,
    shadow_name: str | None,
) -> ShadowMetrics | None:
    if not metrics_path:
        return None
    record = _build_shadow_record(
        primary_provider_name=primary_provider_name,
        primary_response=primary_response,
        request=request,
        shadow_payload=shadow_payload,
        shadow_name=shadow_name,
    )
    return _emit_shadow_metrics(
        record,
        logger=logger,
        metrics_path=metrics_path,
        capture_metrics=capture_metrics,
    )


__all__ = [
    "DEFAULT_METRICS_PATH",
    "_make_shadow_payload",
    "_make_timeout_payload",
    "_finalize_shadow_metrics",
]
