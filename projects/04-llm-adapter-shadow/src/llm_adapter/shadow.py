"""Shadow execution helpers."""
from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from typing import Any

from .observability import EventLogger
from .provider_spi import (
    AsyncProviderSPI,
    ensure_async_provider,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
)
from .shadow_metrics import (
    _build_shadow_record,
    _emit_shadow_metrics,
    _to_path_str,
    MetricsPath,
    ShadowMetrics,
)

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


def _make_timeout_payload(provider_name: str | None, duration_ms: int | None) -> dict[str, Any]:
    payload = {
        "provider": provider_name,
        "ok": False,
        "error": "ShadowTimeout",
        "outcome": "timeout",
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return payload


def _run_shadow_sync(shadow: ProviderSPI, req: ProviderRequest, *, provider_name: str | None) -> dict[str, Any]:
    ts0 = time.time()
    try:
        response = shadow.invoke(req)
    except Exception as exc:  # pragma: no cover - error branch tested via metrics
        return _make_shadow_payload(
            provider_name=provider_name,
            error=exc,
            duration_ms=int((time.time() - ts0) * 1000),
        )
    return _make_shadow_payload(
        provider_name=provider_name,
        response=response,
        duration_ms=int((time.time() - ts0) * 1000),
    )


async def _run_shadow_async(
    shadow_async: AsyncProviderSPI,
    req: ProviderRequest,
    *,
    provider_name: str | None,
) -> dict[str, Any]:
    ts0 = time.time()
    try:
        response = await shadow_async.invoke_async(req)
    except Exception as exc:  # pragma: no cover - logged below
        return _make_shadow_payload(
            provider_name=provider_name,
            error=exc,
            duration_ms=int((time.time() - ts0) * 1000),
        )
    return _make_shadow_payload(
        provider_name=provider_name,
        response=response,
        duration_ms=int((time.time() - ts0) * 1000),
    )


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


def run_with_shadow(
    primary: ProviderSPI,
    shadow: ProviderSPI | None,
    req: ProviderRequest,
    metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    *,
    logger: EventLogger | None = None,
    capture_metrics: bool = False,
) -> ProviderResponse | tuple[ProviderResponse, ShadowMetrics | None]:
    if metrics_path is None:
        logger = None

    shadow_thread: threading.Thread | None = None
    shadow_payload: dict[str, Any] | None = None
    shadow_name: str | None = None
    shadow_started: float | None = None
    metrics_path_str = _to_path_str(metrics_path)

    payload_holder: list[dict[str, Any]] = []
    if shadow is not None:
        shadow_name = shadow.name()
        shadow_started = time.time()

        def _shadow_worker() -> None:
            payload_holder.append(
                _run_shadow_sync(shadow, req, provider_name=shadow_name)
            )

        shadow_thread = threading.Thread(target=_shadow_worker, daemon=True)
        shadow_thread.start()

    try:
        primary_res = primary.invoke(req)
    except Exception:
        if shadow_thread is not None:
            shadow_thread.join(timeout=0)
        raise

    metrics: ShadowMetrics | None = None
    if shadow_thread is not None:
        shadow_thread.join(timeout=10)
        if shadow_thread.is_alive():
            duration_ms = (
                int((time.time() - shadow_started) * 1000)
                if shadow_started is not None
                else None
            )
            shadow_payload = _make_timeout_payload(shadow_name, duration_ms)
        elif payload_holder:
            shadow_payload = dict(payload_holder[-1])
        else:
            shadow_payload = _make_shadow_payload(provider_name=shadow_name)

        metrics = _finalize_shadow_metrics(
            metrics_path=metrics_path_str,
            capture_metrics=capture_metrics,
            logger=logger,
            primary_provider_name=primary.name(),
            primary_response=primary_res,
            request=req,
            shadow_payload=shadow_payload,
            shadow_name=shadow_name,
        )

    if capture_metrics:
        return primary_res, metrics
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
            return await _run_shadow_async(
                shadow_async,
                req,
                provider_name=shadow_name,
            )

        shadow_task = asyncio.create_task(_shadow_worker())

    try:
        primary_res = await primary_async.invoke_async(req)
    except Exception:
        if shadow_task is not None:
            shadow_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shadow_task
        raise

    metrics: ShadowMetrics | None = None
    if shadow_task is not None:
        try:
            shadow_payload = await asyncio.wait_for(shadow_task, timeout=10)
        except TimeoutError:
            shadow_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shadow_task
            duration_ms = (
                int((time.time() - shadow_started) * 1000)
                if shadow_started is not None
                else None
            )
            shadow_payload = _make_timeout_payload(shadow_name, duration_ms)
        except asyncio.CancelledError:  # pragma: no cover - defensive
            shadow_payload = _make_shadow_payload(provider_name=shadow_name)

        if shadow_payload is None:
            shadow_payload = _make_shadow_payload(provider_name=shadow_name)

        metrics = _finalize_shadow_metrics(
            metrics_path=metrics_path_str,
            capture_metrics=capture_metrics,
            logger=logger,
            primary_provider_name=primary_async.name(),
            primary_response=primary_res,
            request=req,
            shadow_payload=shadow_payload,
            shadow_name=shadow_name,
        )

    if capture_metrics:
        return primary_res, metrics
    return primary_res


__all__ = [
    "run_with_shadow",
    "run_with_shadow_async",
    "DEFAULT_METRICS_PATH",
    "ShadowMetrics",
]

