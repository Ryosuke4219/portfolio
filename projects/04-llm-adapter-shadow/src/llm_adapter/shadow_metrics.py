from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .observability import EventLogger, JsonlLogger
from .provider_spi import ProviderRequest, ProviderResponse
from .utils import content_hash

MetricsPath = str | Path | None


@dataclass(slots=True)
class ShadowMetrics:
    payload: dict[str, Any]
    logger: EventLogger | None

    def extend(self, extra: Mapping[str, Any] | None = None) -> None:
        if extra:
            self.payload.update(dict(extra))

    def emit(self, extra: Mapping[str, Any] | None = None) -> None:
        if extra:
            self.extend(extra)
        if self.logger is None:
            return
        payload = dict(self.payload)
        payload.setdefault("ts", int(time.time() * 1000))
        self.logger.emit("shadow_diff", payload)


def _to_path_str(path: MetricsPath) -> str | None:
    return None if path is None else str(Path(path))


def _resolve_shadow_outcome(payload: Mapping[str, Any]) -> str | None:
    outcome = payload.get("outcome")
    if isinstance(outcome, str):
        return outcome
    ok = payload.get("ok")
    if ok is True:
        return "success"
    error = payload.get("error")
    if error == "ShadowTimeout":
        return "timeout"
    if ok is False or error is not None:
        return "error"
    return None


def _build_shadow_record(
    *,
    primary_provider_name: str,
    primary_response: ProviderResponse,
    request: ProviderRequest,
    shadow_payload: Mapping[str, Any] | None,
    shadow_name: str | None,
) -> dict[str, Any]:
    payload: Mapping[str, Any] = shadow_payload or {
        "provider": shadow_name,
        "ok": False,
        "outcome": "error",
    }
    request_inputs = (request.prompt_text, request.options, request.max_tokens)
    request_fingerprint = content_hash("runner", *request_inputs)
    shadow_provider = payload.get("provider", shadow_name)
    shadow_outcome = _resolve_shadow_outcome(payload)
    record: dict[str, Any] = {
        "request_hash": content_hash(primary_provider_name, *request_inputs),
        "request_fingerprint": request_fingerprint,
        "primary_provider": primary_provider_name,
        "primary_latency_ms": primary_response.latency_ms,
        "primary_text_len": len(primary_response.text),
        "primary_token_usage_total": primary_response.token_usage.total,
        "shadow_provider": shadow_provider,
        "shadow_provider_id": shadow_provider,
        "shadow_ok": payload.get("ok"),
        "shadow_outcome": shadow_outcome,
        "shadow_latency_ms": payload.get("latency_ms"),
        "shadow_duration_ms": payload.get("duration_ms"),
        "shadow_error": payload.get("error"),
    }
    if payload.get("latency_ms") is not None:
        record["latency_gap_ms"] = payload["latency_ms"] - primary_response.latency_ms
    if payload.get("text_len") is not None:
        record["shadow_text_len"] = payload["text_len"]
    if payload.get("token_usage_total") is not None:
        record["shadow_token_usage_total"] = payload["token_usage_total"]
    if payload.get("message"):
        record["shadow_error_message"] = payload["message"]
    return record


def _emit_shadow_metrics(
    record: Mapping[str, Any],
    *,
    logger: EventLogger | None,
    metrics_path: str | None,
    capture_metrics: bool,
) -> ShadowMetrics | None:
    event_logger = logger or (JsonlLogger(metrics_path) if metrics_path is not None else None)
    if capture_metrics:
        return ShadowMetrics(dict(record), event_logger)
    if event_logger is not None:
        ShadowMetrics(dict(record), event_logger).emit()
    return None


__all__ = [
    "MetricsPath",
    "ShadowMetrics",
    "_build_shadow_record",
    "_emit_shadow_metrics",
    "_resolve_shadow_outcome",
    "_to_path_str",
]

