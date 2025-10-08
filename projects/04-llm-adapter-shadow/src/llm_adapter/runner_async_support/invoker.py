"""Async provider invocation utilities."""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, cast

from ..errors import FatalError, ProviderSkip, RateLimitError, RetryableError, SkipError
from ..observability import EventLogger
from ..provider_spi import AsyncProviderSPI, ProviderRequest, ProviderResponse, ProviderSPI
from ..runner_shared import RateLimiter, log_provider_call, log_provider_skipped, log_run_metric
from ..shadow import ShadowMetrics, run_with_shadow_async
from ..utils import elapsed_ms
from .shadow_logging import build_shadow_log_metadata


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

        def _with_shadow_metadata(base_metadata: Mapping[str, Any]) -> Mapping[str, Any]:
            if not shadow_log_metadata:
                return base_metadata
            merged_metadata = dict(base_metadata)
            merged_metadata.update(shadow_log_metadata)
            return merged_metadata

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
            enriched_metadata = _with_shadow_metadata(metadata)
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=provider,
                status="error",
                attempts=attempt,
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=err,
                metadata=enriched_metadata,
                shadow_used=shadow is not None,
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
        except RetryableError as err:
            enriched_metadata = _with_shadow_metadata(metadata)
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=provider,
                status="error",
                attempts=attempt,
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=err,
                metadata=enriched_metadata,
                shadow_used=shadow is not None,
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
        except SkipError as err:
            enriched_metadata = _with_shadow_metadata(metadata)
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
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=provider,
                status="error",
                attempts=attempt,
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=err,
                metadata=enriched_metadata,
                shadow_used=shadow is not None,
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
            enriched_metadata = _with_shadow_metadata(metadata)
            log_run_metric(
                event_logger,
                request_fingerprint=request_fingerprint,
                request=request,
                provider=provider,
                status="error",
                attempts=attempt,
                latency_ms=elapsed_ms(attempt_started),
                tokens_in=None,
                tokens_out=None,
                cost_usd=0.0,
                error=err,
                metadata=enriched_metadata,
                shadow_used=shadow is not None,
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


__all__ = ["AsyncProviderInvoker"]
