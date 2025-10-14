from __future__ import annotations

from typing import Any

import pytest
from llm_adapter.errors import TimeoutError
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from llm_adapter.runner_config import RunnerConfig
from llm_adapter.runner_sync import ProviderInvocationResult, Runner
from llm_adapter.runner_sync_modes import SequentialStrategy

from .conftest import (
    _make_context,
    _RecordingLogger,
    _SuccessfulProvider,
)


def test_sequential_strategy_handles_successful_provider_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [_SuccessfulProvider("primary")]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    response = ProviderResponse(
        "ok",
        latency_ms=12,
        token_usage=TokenUsage(prompt=3, completion=4),
    )

    def fake_invoke(
        provider: Any,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        **_: Any,
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=response,
            error=None,
            latency_ms=5,
            tokens_in=3,
            tokens_out=4,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)

    result = strategy.execute(context)

    assert result is response
    run_metric_events = [event for event in logger.events if event[0] == "run_metric"]
    assert len(run_metric_events) == 1
    _, payload = run_metric_events[0]
    assert payload["status"] == "ok"
    assert payload["tokens_in"] == 3
    assert payload["tokens_out"] == 4


def test_sequential_run_metric_reports_response_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [_SuccessfulProvider("primary")]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    response = ProviderResponse(
        "ok",
        latency_ms=12,
        token_usage=TokenUsage(prompt=0, completion=0),
    )

    def fake_invoke(
        provider: Any,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        **_: Any,
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=response,
            error=None,
            latency_ms=None,
            tokens_in=0,
            tokens_out=0,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)
    monkeypatch.setattr(
        "llm_adapter.runner_sync_sequential.elapsed_ms",
        lambda _: 99,
    )

    result = strategy.execute(context)

    assert result is response
    run_metric_events = [event for event in logger.events if event[0] == "run_metric"]
    assert len(run_metric_events) == 1
    _, payload = run_metric_events[0]
    assert payload["latency_ms"] == 12


def test_sequential_strategy_logs_error_metric_before_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [_SuccessfulProvider("primary"), _SuccessfulProvider("secondary")]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    success_response = ProviderResponse(
        "ok",
        latency_ms=8,
        token_usage=TokenUsage(prompt=2, completion=3),
    )

    invocation_results = [
        ProviderInvocationResult(
            provider=providers[0],
            attempt=1,
            total_providers=2,
            response=None,
            error=TimeoutError("boom"),
            latency_ms=7,
            tokens_in=5,
            tokens_out=1,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
        ProviderInvocationResult(
            provider=providers[1],
            attempt=2,
            total_providers=2,
            response=success_response,
            error=None,
            latency_ms=4,
            tokens_in=2,
            tokens_out=3,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
    ]

    def fake_invoke(
        provider: Any,
        request: ProviderRequest,
        *,
        attempt: int,
        total_providers: int,
        **_: Any,
    ) -> ProviderInvocationResult:
        result = invocation_results.pop(0)
        assert result.provider is provider
        assert result.attempt == attempt
        assert result.total_providers == total_providers
        return result

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)

    result = strategy.execute(context)

    assert result is success_response
    run_metric_events = [event for event in logger.events if event[0] == "run_metric"]
    assert len(run_metric_events) == 2
    _, failure_payload = run_metric_events[0]
    assert failure_payload["provider_id"] == "primary"
    assert failure_payload["outcome"] == "error"
