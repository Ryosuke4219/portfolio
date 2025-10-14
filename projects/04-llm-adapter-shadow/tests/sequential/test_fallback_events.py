from __future__ import annotations

from typing import Any

import pytest
from llm_adapter.errors import AuthError, TimeoutError
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from llm_adapter.runner_config import RunnerConfig
from llm_adapter.runner_sync import ProviderInvocationResult, Runner
from llm_adapter.runner_sync_modes import SequentialStrategy

from .conftest import _FailingProvider, _make_context, _RecordingLogger


def test_sequential_strategy_emits_fallback_for_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [
        _FailingProvider("primary", TimeoutError("boom")),
        _FailingProvider("secondary", TimeoutError("boom")),
    ]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    response = ProviderResponse(
        "ok",
        latency_ms=10,
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
        if provider.name() == "primary":
            return ProviderInvocationResult(
                provider=provider,
                attempt=attempt,
                total_providers=total_providers,
                response=None,
                error=AuthError("bad key"),
                latency_ms=5,
                tokens_in=None,
                tokens_out=None,
                shadow_metrics=None,
                shadow_metrics_extra=None,
                provider_call_logged=True,
            )
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=response,
            error=None,
            latency_ms=5,
            tokens_in=0,
            tokens_out=0,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)

    result = strategy.execute(context)

    assert result is response
    fallback_events = [event for event in logger.events if event[0] == "provider_fallback"]
    assert len(fallback_events) == 1
    event_type, payload = fallback_events[0]
    assert event_type == "provider_fallback"
    assert payload["provider"] == "primary"
    assert payload["attempt"] == 1
