from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.llm_adapter.errors import TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner, Runner
import src.llm_adapter.runner_async_modes as runner_async_modes
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode

from .conftest import _AsyncProbeProvider, _CapturingLogger, _FakeClock


def test_async_runner_enforces_rpm(monkeypatch: pytest.MonkeyPatch) -> None:
    request = ProviderRequest(model="gpt-test", prompt="hi")
    clock = _FakeClock()
    monkeypatch.setattr("src.llm_adapter.runner_shared.time.monotonic", clock.monotonic)
    monkeypatch.setattr("src.llm_adapter.runner_shared.time.sleep", clock.sleep)
    monkeypatch.setattr("src.llm_adapter.runner_shared.asyncio.sleep", clock.async_sleep)

    call_times: list[float] = []

    class _RecordingAsyncProvider:
        def name(self) -> str:
            return "timed"

        def capabilities(self) -> set[str]:
            return set()

        async def invoke_async(self, _: ProviderRequest) -> ProviderResponse:
            call_times.append(clock.monotonic())
            return ProviderResponse(
                text="ok",
                latency_ms=10,
                token_usage=TokenUsage(prompt=1, completion=1),
                model="timed-model",
            )

    runner = AsyncRunner([_RecordingAsyncProvider()], config=RunnerConfig(rpm=30))

    async def _execute() -> None:
        await runner.run_async(request)
        await runner.run_async(request)

    asyncio.run(asyncio.wait_for(_execute(), timeout=0.1))

    assert call_times[1] - call_times[0] >= 2.0


def test_async_runner_matches_sync(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    sync_runner = Runner([primary])
    async_runner = AsyncRunner([primary])

    sync_request = ProviderRequest(
        prompt="hello",
        metadata={"trace_id": "t1"},
        model="primary-model",
    )
    async_request = ProviderRequest(
        prompt="hello",
        metadata={"trace_id": "t1"},
        model="primary-model",
    )

    sync_metrics = tmp_path / "sync-metrics.jsonl"
    async_metrics = tmp_path / "async-metrics.jsonl"

    sync_response = sync_runner.run(sync_request, shadow_metrics_path=sync_metrics)
    async_response = asyncio.run(
        asyncio.wait_for(
            async_runner.run_async(async_request, shadow_metrics_path=async_metrics),
            timeout=0.5,
        )
    )

    assert async_response.text == sync_response.text
    assert async_response.model == sync_response.model
    assert async_metrics.exists()


@pytest.mark.parametrize(
    ("mode", "strategy_name"),
    [
        (RunnerMode.SEQUENTIAL, "SequentialRunStrategy"),
        (RunnerMode.PARALLEL_ANY, "ParallelAnyRunStrategy"),
        (RunnerMode.PARALLEL_ALL, "ParallelAllRunStrategy"),
        (RunnerMode.CONSENSUS, "ConsensusRunStrategy"),
    ],
)
def test_async_runner_strategy_selection(
    monkeypatch: pytest.MonkeyPatch, mode: RunnerMode, strategy_name: str
) -> None:
    strategy_cls = getattr(runner_async_modes, strategy_name)
    original_run = strategy_cls.run
    called: list[str] = []

    async def _wrapped(self: object, context: object) -> Any:
        called.append(strategy_name)
        return await original_run(self, context)

    monkeypatch.setattr(strategy_cls, "run", _wrapped)

    providers = [
        _AsyncProbeProvider("p1", delay=0.0, text="ok"),
        _AsyncProbeProvider("p2", delay=0.0, text="ok"),
    ]
    config_kwargs: dict[str, Any] = {"mode": mode}
    if mode == RunnerMode.CONSENSUS:
        from src.llm_adapter.runner_config import ConsensusConfig

        config_kwargs["consensus"] = ConsensusConfig()
    runner = AsyncRunner(providers, config=RunnerConfig(**config_kwargs))
    request = ProviderRequest(model="gpt-test", prompt="hello")

    asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.1))

    assert called == [strategy_name]


def test_async_runner_emits_failure_event() -> None:
    logger = _CapturingLogger()
    provider = _AsyncProbeProvider(
        "flaky",
        delay=0.0,
        text="nope",
        failures=[TimeoutError("boom")],
    )
    runner = AsyncRunner(
        [provider],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.SEQUENTIAL),
    )
    request = ProviderRequest(model="gpt-test", prompt="fail")

    async def _execute() -> None:
        await runner.run_async(request)

    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(_execute(), timeout=0.1))

    events = logger.of_type("provider_chain_failed")
    assert len(events) == 1
    event = events[0]
    assert event["provider_attempts"] == 1
    assert event["providers"] == ["flaky"]
    assert event["last_error_type"] == "TimeoutError"
