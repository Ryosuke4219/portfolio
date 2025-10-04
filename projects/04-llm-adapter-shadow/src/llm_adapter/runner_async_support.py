"""Support utilities for :mod:`llm_adapter.runner_async`."""
from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any, cast

from .errors import FatalError, ProviderSkip, RateLimitError, RetryableError, SkipError
from .observability import EventLogger
from .parallel_exec import ParallelExecutionError
from .provider_spi import (
    AsyncProviderSPI,
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
)
from .runner_async_modes import AsyncRunContext, collect_failure_details, WorkerResult
from .runner_shared import log_provider_call, log_provider_skipped, RateLimiter
from .shadow import run_with_shadow_async, ShadowMetrics
from .utils import elapsed_ms

TypingMapping = Mapping


def build_shadow_log_metadata(shadow_metrics: ShadowMetrics | None) -> dict[str, Any]:
    if shadow_metrics is None:
        return {}
    payload: Mapping[str, Any] = shadow_metrics.payload
    metadata: dict[str, Any] = {}
    latency = payload.get("shadow_latency_ms")
    if isinstance(latency, (int, float)):
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


class AsyncProviderInvoker:
    """Encapsulates provider invocation with logging and rate limiting."""

    def __init__(self, *, rate_limiter: RateLimiter | None) -> None:
        self._rate_limiter = rate_limiter

    async def invoke(
        self,
        provider: ProviderSPI | AsyncProviderSPI,
        async_provider: AsyncProviderSPI,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        event_logger: EventLogger | None,
        request_fingerprint: str,
        metadata: Mapping[str, Any],
        shadow: ProviderSPI | AsyncProviderSPI | None,
        shadow_async: AsyncProviderSPI | None,
        metrics_path: str | None,
        capture_shadow_metrics: bool,
    ) -> tuple[ProviderResponse, ShadowMetrics | None]:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire_async()
        attempt_started = time.time()
        shadow_metrics: ShadowMetrics | None = None
        shadow_log_metadata: dict[str, Any] = {}
        response: ProviderResponse
        try:
            should_capture = shadow_async is not None
            if should_capture:
                response_with_metrics = await run_with_shadow_async(
                    async_provider,
                    shadow_async,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=True,
                )
                response, shadow_metrics = cast(
                    tuple[ProviderResponse, ShadowMetrics | None],
                    response_with_metrics,
                )
                shadow_log_metadata = build_shadow_log_metadata(shadow_metrics)
                if not capture_shadow_metrics and shadow_metrics is not None:
                    shadow_metrics.emit()
                    shadow_metrics = None
            else:
                response_only = await run_with_shadow_async(
                    async_provider,
                    shadow_async,
                    request,
                    metrics_path=metrics_path,
                    logger=event_logger,
                    capture_metrics=False,
                )
                response = cast(ProviderResponse, response_only)
        except RateLimitError as err:
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        except RetryableError as err:
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        except SkipError as err:
            if isinstance(err, ProviderSkip):
                log_provider_skipped(
                    event_logger,
                    request_fingerprint=request_fingerprint,
                    provider=provider,
                    request=request,
                    attempt=attempt,
                    total_providers=total_providers,
                    error=err,
                )
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        except FatalError as err:
            log_provider_call(
                event_logger,
                request_fingerprint=request_fingerprint,
                provider=provider,
                request=request,
                attempt=attempt,
                total_providers=total_providers,
                status="error",
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                error=err,
                metadata=metadata,
                shadow_used=shadow is not None,
                allow_private_model=True,
            )
            raise
        token_usage = response.token_usage
        if shadow_log_metadata:
            enriched_metadata = dict(metadata)
            enriched_metadata.update(shadow_log_metadata)
        else:
            enriched_metadata = metadata
        log_provider_call(
            event_logger,
            request_fingerprint=request_fingerprint,
            provider=provider,
            request=request,
            attempt=attempt,
            total_providers=total_providers,
            status="ok",
            latency_ms=response.latency_ms,
            tokens_in=token_usage.prompt,
            tokens_out=token_usage.completion,
            error=None,
            metadata=enriched_metadata,
            shadow_used=shadow is not None,
            allow_private_model=True,
        )
        return response, shadow_metrics


def emit_consensus_failure(
    *,
    context: AsyncRunContext,
    results: list[WorkerResult] | None,
    failure_details: list[dict[str, str]] | None,
    last_error: Exception | None,
) -> tuple[list[dict[str, str]] | None, Exception | None]:
    """Aggregate consensus failures and emit metrics/errors."""

    updated_details = failure_details
    if results is not None:
        for _, _, _, metrics in results:
            if metrics is not None:
                metrics.emit()
        no_success = not any(len(entry) >= 3 and entry[2] is not None for entry in results)
        if no_success and not updated_details:
            updated_details = collect_failure_details(context)
    elif not updated_details:
        updated_details = collect_failure_details(context)

    updated_error = last_error
    if updated_details and (
        updated_error is None or not isinstance(updated_error, ParallelExecutionError)
    ):
        detail_text = "; ".join(
            f"{item['provider']} (attempt {item['attempt']}): {item['summary']}"
            for item in updated_details
        )
        message = "all workers failed"
        if detail_text:
            message = f"{message}: {detail_text}"
        updated_error = ParallelExecutionError(message, failures=updated_details)

    return updated_details, updated_error


__all__ = [
    "AsyncProviderInvoker",
    "build_shadow_log_metadata",
    "emit_consensus_failure",
]
