"""Asynchronous shadow execution helpers."""

from __future__ import annotations

import asyncio
import contextlib
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
from .shadow_metrics import _to_path_str, MetricsPath, ShadowMetrics
from .shadow_shared import (
    _finalize_shadow_metrics,
    _make_shadow_payload,
    _make_timeout_payload,
    DEFAULT_METRICS_PATH,
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
    "run_with_shadow_async",
    "_run_shadow_async",
]
