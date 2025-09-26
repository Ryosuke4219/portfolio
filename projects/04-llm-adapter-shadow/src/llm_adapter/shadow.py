"""Shadow execution helpers."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .metrics import log_event
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .utils import content_hash

MetricsPath = str | Path | None
DEFAULT_METRICS_PATH = "artifacts/runs-metrics.jsonl"


def _to_path_str(path: MetricsPath) -> str | None:
    if path is None:
        return None
    return str(Path(path))


def run_with_shadow(
    primary: ProviderSPI,
    shadow: ProviderSPI | None,
    req: ProviderRequest,
    metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
) -> ProviderResponse:
    """Invoke ``primary`` while optionally mirroring the call on ``shadow``.

    The shadow execution runs on a background thread and *never* affects the
    primary result. Metrics about both executions are appended to a JSONL file
    so they can be analysed offline.
    """

    shadow_thread: threading.Thread | None = None
    shadow_payload: dict[str, Any] = {}
    shadow_name: str | None = None
    metrics_path_str = _to_path_str(metrics_path)

    if shadow is not None:
        shadow_name = shadow.name()

        def _shadow_worker() -> None:
            ts0 = time.time()
            try:
                response = shadow.invoke(req)
            except Exception as exc:  # pragma: no cover - error branch tested via metrics
                shadow_payload.update(
                    {
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                        "provider": shadow_name,
                    }
                )
            else:
                shadow_payload.update(
                    {
                        "ok": True,
                        "provider": shadow_name,
                        "latency_ms": response.latency_ms,
                        "text_len": len(response.text),
                        "token_usage_total": response.token_usage.total,
                    }
                )
            finally:
                shadow_payload["duration_ms"] = int((time.time() - ts0) * 1000)

        shadow_thread = threading.Thread(target=_shadow_worker, daemon=True)
        shadow_thread.start()

    try:
        primary_res = primary.invoke(req)
    except Exception:
        if shadow_thread is not None:
            shadow_thread.join(timeout=0)
        raise

    if shadow_thread is not None:
        shadow_thread.join(timeout=10)
        if shadow_thread.is_alive():
            shadow_payload.setdefault("provider", shadow_name)
            shadow_payload.update({"ok": False, "error": "ShadowTimeout"})

        if metrics_path_str:
            primary_text_len = len(primary_res.text)
            request_fingerprint = content_hash(
                "runner", req.prompt_text, req.options, req.max_tokens
            )
            record: dict[str, Any] = {
                "request_hash": content_hash(
                    primary.name(), req.prompt_text, req.options, req.max_tokens
                ),
                "request_fingerprint": request_fingerprint,
                "primary_provider": primary.name(),
                "primary_latency_ms": primary_res.latency_ms,
                "primary_text_len": primary_text_len,
                "primary_token_usage_total": primary_res.token_usage.total,
                "shadow_provider": shadow_payload.get("provider", shadow_name),
                "shadow_ok": shadow_payload.get("ok"),
                "shadow_latency_ms": shadow_payload.get("latency_ms"),
                "shadow_duration_ms": shadow_payload.get("duration_ms"),
                "shadow_error": shadow_payload.get("error"),
            }

            if shadow_payload.get("latency_ms") is not None:
                record["latency_gap_ms"] = shadow_payload["latency_ms"] - primary_res.latency_ms

            if shadow_payload.get("text_len") is not None:
                record["shadow_text_len"] = shadow_payload["text_len"]

            if shadow_payload.get("token_usage_total") is not None:
                record["shadow_token_usage_total"] = shadow_payload["token_usage_total"]

            if shadow_payload.get("message"):
                record["shadow_error_message"] = shadow_payload["message"]

            log_event("shadow_diff", metrics_path_str, **record)

    return primary_res


__all__ = ["run_with_shadow", "DEFAULT_METRICS_PATH"]
