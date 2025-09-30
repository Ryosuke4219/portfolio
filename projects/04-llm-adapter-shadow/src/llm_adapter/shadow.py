"""Shadow execution helpers."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import contextlib
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any

from .observability import EventLogger, JsonlLogger
from .provider_spi import (
    AsyncProviderSPI,
    ensure_async_provider,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
)
from .utils import content_hash

MetricsPath = str | Path | None
DEFAULT_METRICS_PATH = "artifacts/runs-metrics.jsonl"


@dataclass(slots=True)
class ShadowMetrics:
    payload: dict[str, Any]
    logger: EventLogger | None

    def extend(self, extra: Mapping[str, Any] | None = None) -> None:
        if not extra:
            return
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
    if path is None:
        return None
    return str(Path(path))


def _tokens_total(res: ProviderResponse) -> int:
    usage = res.token_usage
    return usage.total


def _build_shadow_record(
    *,
    primary_provider_name: str,
    primary_response: ProviderResponse,
    request: ProviderRequest,
    shadow_payload: Mapping[str, Any] | None,
    shadow_name: str | None,
) -> dict[str, Any]:
    """Compose the metrics payload for a shadow run."""

    payload: Mapping[str, Any] = shadow_payload or {"provider": shadow_name, "ok": False}
    primary_text_len = len(primary_response.text)
    request_fingerprint = content_hash(
        "runner", request.prompt_text, request.options, request.max_tokens
    )
    record: dict[str, Any] = {
        "request_hash": content_hash(
            primary_provider_name, request.prompt_text, request.options, request.max_tokens
        ),
        "request_fingerprint": request_fingerprint,
        "primary_provider": primary_provider_name,
        "primary_latency_ms": primary_response.latency_ms,
        "primary_text_len": primary_text_len,
        "primary_token_usage_total": _tokens_total(primary_response),
        "shadow_provider": payload.get("provider", shadow_name),
        "shadow_ok": payload.get("ok"),
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
    """Emit metrics or return them for deferred emission."""

    event_logger = logger
    if event_logger is None and metrics_path is not None:
        event_logger = JsonlLogger(metrics_path)

    if capture_metrics:
        return ShadowMetrics(dict(record), event_logger)

    if event_logger is not None:
        metrics = ShadowMetrics(dict(record), event_logger)
        metrics.emit()

    return None


def run_with_shadow(
    primary: ProviderSPI,
    shadow: ProviderSPI | None,
    req: ProviderRequest,
    metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    *,
    logger: EventLogger | None = None,
    capture_metrics: bool = False,
) -> ProviderResponse | tuple[ProviderResponse, ShadowMetrics | None]:
    """Invoke ``primary`` while optionally mirroring the call on ``shadow``.

    The shadow execution runs on a background thread and *never* affects the
    primary result. Metrics about both executions are appended to a JSONL file
    so they can be analysed offline.
    """

    if metrics_path is None:
        logger = None

    shadow_thread: threading.Thread | None = None
    shadow_payload: dict[str, Any] | None = None
    shadow_name: str | None = None
    shadow_started: float | None = None
    metrics_path_str = _to_path_str(metrics_path)

    if shadow is not None:
        shadow_name = shadow.name()
        shadow_started = time.time()
        payload_holder: list[dict[str, Any]] = []

        def _shadow_worker() -> None:
            ts0 = time.time()
            payload: dict[str, Any]
            try:
                response = shadow.invoke(req)
            except Exception as exc:  # pragma: no cover - error branch tested via metrics
                payload = {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "provider": shadow_name,
                }
            else:
                payload = {
                    "ok": True,
                    "provider": shadow_name,
                    "latency_ms": response.latency_ms,
                    "text_len": len(response.text),
                    "token_usage_total": _tokens_total(response),
                }
            finally:
                payload["duration_ms"] = int((time.time() - ts0) * 1000)
                payload_holder.append(payload)

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
            duration_ms = 0
            if shadow_started is not None:
                duration_ms = int((time.time() - shadow_started) * 1000)
            shadow_payload = {
                "provider": shadow_name,
                "ok": False,
                "error": "ShadowTimeout",
                "duration_ms": duration_ms,
            }
        elif payload_holder:
            shadow_payload = dict(payload_holder[-1])
        else:
            shadow_payload = {"provider": shadow_name, "ok": False}

        if metrics_path_str:
            record = _build_shadow_record(
                primary_provider_name=primary.name(),
                primary_response=primary_res,
                request=req,
                shadow_payload=shadow_payload,
                shadow_name=shadow_name,
            )
            metrics = _emit_shadow_metrics(
                record,
                logger=logger,
                metrics_path=metrics_path_str,
                capture_metrics=capture_metrics,
            )

            if capture_metrics:
                return primary_res, metrics

    if capture_metrics:
        return primary_res, None

    return primary_res


async def run_with_shadow_async(
    primary: ProviderSPI | AsyncProviderSPI,
    shadow: ProviderSPI | AsyncProviderSPI | None,
    req: ProviderRequest,
    metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    *,
    logger: EventLogger | None = None,
    capture_metrics: bool = False,
) -> ProviderResponse | tuple[ProviderResponse, ShadowMetrics | None]:
    primary_async = ensure_async_provider(primary)
    shadow_async = ensure_async_provider(shadow) if shadow is not None else None

    if metrics_path is None:
        logger = None

    shadow_task: asyncio.Task[dict[str, Any]] | None = None
    shadow_payload: dict[str, Any] | None = None
    shadow_name: str | None = None
    shadow_started: float | None = None
    metrics_path_str = _to_path_str(metrics_path)

    if shadow_async is not None:
        shadow_name = shadow_async.name()
        shadow_started = time.time()

        async def _shadow_worker() -> dict[str, Any]:
            ts0 = time.time()
            try:
                response = await shadow_async.invoke_async(req)
            except Exception as exc:  # pragma: no cover - logged below
                payload = {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "provider": shadow_name,
                }
            else:
                payload = {
                    "ok": True,
                    "provider": shadow_name,
                    "latency_ms": response.latency_ms,
                    "text_len": len(response.text),
                    "token_usage_total": _tokens_total(response),
                }
            payload["duration_ms"] = int((time.time() - ts0) * 1000)
            return payload

        shadow_task = asyncio.create_task(_shadow_worker())

    try:
        primary_res = await primary_async.invoke_async(req)
    except Exception:
        if shadow_task is not None:
            shadow_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shadow_task
        raise

    if shadow_task is not None:
        try:
            shadow_payload = await asyncio.wait_for(shadow_task, timeout=10)
        except TimeoutError:
            shadow_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shadow_task
            duration_ms = 0
            if shadow_started is not None:
                duration_ms = int((time.time() - shadow_started) * 1000)
            shadow_payload = {
                "provider": shadow_name,
                "ok": False,
                "error": "ShadowTimeout",
                "duration_ms": duration_ms,
            }
        except asyncio.CancelledError:  # pragma: no cover - defensive
            shadow_payload = {"provider": shadow_name, "ok": False}

        if shadow_payload is None:
            shadow_payload = {"provider": shadow_name, "ok": False}

        if metrics_path_str:
            record = _build_shadow_record(
                primary_provider_name=primary_async.name(),
                primary_response=primary_res,
                request=req,
                shadow_payload=shadow_payload,
                shadow_name=shadow_name,
            )
            metrics = _emit_shadow_metrics(
                record,
                logger=logger,
                metrics_path=metrics_path_str,
                capture_metrics=capture_metrics,
            )

            if capture_metrics:
                return primary_res, metrics

    if capture_metrics:
        return primary_res, None

    return primary_res


__all__ = [
    "run_with_shadow",
    "run_with_shadow_async",
    "DEFAULT_METRICS_PATH",
    "ShadowMetrics",
]
