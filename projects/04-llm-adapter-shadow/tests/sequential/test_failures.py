from __future__ import annotations

from typing import Any

import pytest

from src.llm_adapter.errors import AllFailedError, TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner_config import RunnerConfig
from src.llm_adapter.runner_sync import ProviderInvocationResult, Runner
from src.llm_adapter.runner_sync_modes import SequentialStrategy

from .conftest import _FailingProvider, _make_context, _RecordingLogger


def test_sequential_raises_all_failed_error_with_cause() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hello")
    first_error = TimeoutError("slow")
    second_error = TimeoutError("boom")
    providers = [
        _FailingProvider("first", first_error),
        _FailingProvider("second", second_error),
    ]
    runner = Runner(providers, config=RunnerConfig())

    with pytest.raises(AllFailedError) as exc_info:
        runner.run(request)

    error = exc_info.value
    assert error.__cause__ is second_error
    assert providers[0].calls == 1
    assert providers[1].calls == 1


def test_sequential_strategy_all_failed_logs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        _FailingProvider("primary", TimeoutError("slow")),
        _FailingProvider("secondary", TimeoutError("boom")),
    ]
    runner = Runner(providers, config=RunnerConfig())
    strategy = SequentialStrategy()
    logger = _RecordingLogger()
    context = _make_context(runner, logger=logger)

    errors = {
        "primary": TimeoutError("slow"),
        "secondary": TimeoutError("boom"),
    }

    def fake_invoke(
        provider: Any,
        request: Any,
        *,
        attempt: int,
        total_providers: int,
        **_: Any,
    ) -> ProviderInvocationResult:
        error = errors[provider.name()]
        return ProviderInvocationResult(
            provider=provider,
            attempt=attempt,
            total_providers=total_providers,
            response=None,
            error=error,
            latency_ms=5,
            tokens_in=None,
            tokens_out=None,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )

    monkeypatch.setattr(runner, "_invoke_provider_sync", fake_invoke)

    log_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_log_run_metric(*args: Any, **kwargs: Any) -> None:
        log_calls.append((args, kwargs))

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync_sequential.log_run_metric",
        fake_log_run_metric,
    )

    with pytest.raises(AllFailedError) as exc_info:
        strategy.execute(context)

    message = str(exc_info.value)
    assert "primary (attempt 1)" in message
    assert "secondary (attempt 2)" in message
    assert len(log_calls) == 1
    assert log_calls[0][1]["status"] == "error"
