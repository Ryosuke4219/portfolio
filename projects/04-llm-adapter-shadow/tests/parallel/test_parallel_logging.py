from __future__ import annotations

from concurrent.futures import CancelledError

import pytest

from src.llm_adapter.errors import TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner_sync_invocation import (
    CancelledResultsBuilder,
    ParallelResultLogger,
    ProviderInvocationResult,
)

from ..parallel_helpers import _StaticProvider


def test_cancelled_results_builder_populates_cancelled_slots() -> None:
    run_started = 100.0
    builder = CancelledResultsBuilder(run_started=run_started, elapsed_ms=lambda _: 42)
    providers = [
        _StaticProvider("cancel-a", text="unused", latency_ms=1),
        _StaticProvider("cancel-b", text="unused", latency_ms=1),
    ]
    results: list[ProviderInvocationResult | None] = [None, None]

    builder.apply(
        results,
        providers=providers,
        cancelled_indices=(0, 1),
        total_providers=len(providers),
    )

    for index, result in enumerate(results, start=1):
        assert result is not None
        assert result.provider.name() == providers[index - 1].name()
        assert isinstance(result.error, CancelledError)
        assert result.latency_ms == 42
        assert result.provider_call_logged is False
        assert result.attempt == index
        assert result.total_providers == len(providers)


def test_parallel_result_logger_skips_and_avoids_duplicate_logging() -> None:
    provider = _StaticProvider("logger", text="ok", latency_ms=5)
    request = ProviderRequest(prompt="hello", model="m")
    metadata: dict[str, object] = {"trace": "abc"}
    request_fingerprint = "fingerprint"
    shadow_used = False
    run_started = 0.0
    elapsed_calls: list[float] = []

    def _elapsed(_: float) -> int:
        elapsed_calls.append(1.0)
        return 99

    provider_call_log: list[dict[str, object]] = []
    run_metric_log: list[dict[str, object]] = []

    def _log_provider_call(event_logger: object, **record: object) -> None:
        provider_call_log.append(record)

    def _log_run_metric(event_logger: object, **record: object) -> None:
        run_metric_log.append(record)

    success_result = ProviderInvocationResult(
        provider=provider,
        attempt=2,
        total_providers=3,
        response=ProviderResponse(
            text="done",
            latency_ms=7,
            token_usage=TokenUsage(prompt=1, completion=2),
            model="m",
            finish_reason="stop",
        ),
        error=None,
        latency_ms=7,
        tokens_in=1,
        tokens_out=2,
        shadow_metrics=None,
        shadow_metrics_extra=None,
        provider_call_logged=False,
    )
    skipped_result = ProviderInvocationResult(
        provider=provider,
        attempt=1,
        total_providers=3,
        response=None,
        error=CancelledError(),
        latency_ms=None,
        tokens_in=None,
        tokens_out=None,
        shadow_metrics=None,
        shadow_metrics_extra=None,
        provider_call_logged=False,
    )
    already_logged_result = ProviderInvocationResult(
        provider=provider,
        attempt=3,
        total_providers=3,
        response=None,
        error=TimeoutError("boom"),
        latency_ms=None,
        tokens_in=None,
        tokens_out=None,
        shadow_metrics=None,
        shadow_metrics_extra=None,
        provider_call_logged=True,
    )

    logger = ParallelResultLogger(
        log_provider_call=_log_provider_call,
        log_run_metric=_log_run_metric,
        elapsed_ms=_elapsed,
    )

    logger.log_results(
        [skipped_result, success_result, already_logged_result],
        event_logger=None,
        request=request,
        request_fingerprint=request_fingerprint,
        metadata=metadata,
        run_started=run_started,
        shadow_used=shadow_used,
        skip=(skipped_result,),
    )

    assert provider_call_log == [
        {
            "request_fingerprint": request_fingerprint,
            "provider": provider,
            "request": request,
            "attempt": success_result.attempt,
            "total_providers": success_result.total_providers,
            "status": "ok",
            "latency_ms": success_result.latency_ms,
            "tokens_in": success_result.tokens_in,
            "tokens_out": success_result.tokens_out,
            "error": None,
            "metadata": metadata,
            "shadow_used": shadow_used,
        }
    ]
    assert len(run_metric_log) == 2
    attempts = {entry["attempts"] for entry in run_metric_log}
    assert attempts == {success_result.attempt, already_logged_result.attempt}
    assert skipped_result.provider_call_logged is False
    assert success_result.provider_call_logged is True
    assert already_logged_result.provider_call_logged is True
    assert elapsed_calls == [1.0]
