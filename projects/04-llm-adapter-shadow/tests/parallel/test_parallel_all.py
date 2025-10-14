from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from llm_adapter.errors import TimeoutError
from llm_adapter.parallel_exec import run_parallel_all_async, run_parallel_all_sync
from llm_adapter.provider_spi import ProviderRequest
from llm_adapter.providers.mock import MockProvider
from llm_adapter.runner import AsyncRunner, ParallelAllResult, Runner
from llm_adapter.runner_config import BackoffPolicy, RunnerConfig, RunnerMode

from ..parallel_helpers import (
    _install_recording_executor,
    _read_metrics,
    _RetryProbeProvider,
    _StaticProvider,
    _worker_for,
)

# --- ALL モードの戻り値 ---


def test_parallel_all_primitives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm_adapter.providers.mock.random.random", lambda: 0.0)
    request = ProviderRequest(prompt="hello", model="m")
    providers = [
        MockProvider("p1", base_latency_ms=1, error_markers=set()),
        MockProvider("p2", base_latency_ms=2, error_markers=set()),
    ]
    collected = run_parallel_all_sync(
        tuple(_worker_for(provider, request) for provider in providers)
    )
    assert [res.text for res in collected] == ["echo(p1): hello", "echo(p2): hello"]


def test_runner_parallel_all_returns_full_result() -> None:
    providers = [
        _StaticProvider("p1", "response-1", latency_ms=5),
        _StaticProvider("p2", "response-2", latency_ms=7),
    ]
    runner = Runner(
        providers,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hello", model="m-parallel")

    result = runner.run(request)

    assert isinstance(result, ParallelAllResult)
    assert [response.text for response in result.responses] == [
        "response-1",
        "response-2",
    ]
    assert result.text == "response-1"


def test_async_runner_parallel_all_returns_full_result() -> None:
    async def _run() -> None:
        providers = [
            _StaticProvider("p1", "async-1", latency_ms=5),
            _StaticProvider("p2", "async-2", latency_ms=7),
        ]
        runner = AsyncRunner(
            providers,
            config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL, max_concurrency=2),
        )
        request = ProviderRequest(prompt="hello", model="m-async-parallel")

        result = await runner.run_async(request)

        assert isinstance(result, ParallelAllResult)
        assert [response.text for response in result.responses] == [
            "async-1",
            "async-2",
        ]
        assert result.text == "async-1"

    asyncio.run(_run())


def test_runner_parallel_all_exhausts_timeout_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda delay: sleep_calls.append(delay))
    executors = _install_recording_executor(monkeypatch)
    provider = _RetryProbeProvider(
        "retry-all",
        [TimeoutError("first"), TimeoutError("second")],
        latency_s=0.001,
    )
    runner = Runner(
        [provider, provider],
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ALL,
            max_concurrency=1,
            max_attempts=2,
            backoff=BackoffPolicy(),
        ),
    )
    request = ProviderRequest(prompt="timeout", model="parallel-all-retry")
    metrics_path = tmp_path / "parallel_all_retry.jsonl"

    with pytest.raises(TimeoutError):
        runner.run(request, shadow=None, shadow_metrics_path=metrics_path)

    assert provider.call_count == 2
    assert len(sleep_calls) == provider.call_count
    executor = executors[-1]
    assert len(executor.submitted) == provider.call_count
    assert all(f.done() or f.cancelled() for f in executor.submitted)

    events = _read_metrics(metrics_path)
    provider_calls = sorted(
        (event for event in events if event["event"] == "provider_call"),
        key=lambda event: event["attempt"],
    )
    assert [event["attempt"] for event in provider_calls] == [1, 2]
    assert all(event["error_type"] == "TimeoutError" for event in provider_calls)
    run_metrics = [event for event in events if event["event"] == "run_metric"]
    assert [event["attempts"] for event in run_metrics] == [1, 2]


def test_run_parallel_all_async_on_retry_future() -> None:
    async def _run() -> None:
        attempts = 0

        async def worker() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("first failure")
            return "ok"

        retry_log: list[tuple[int, int, str]] = []
        loop = asyncio.get_running_loop()

        def on_retry(
            index: int, attempt: int, exc: BaseException
        ) -> asyncio.Future[float | None]:
            retry_log.append((index, attempt, type(exc).__name__))
            future: asyncio.Future[float | None] = loop.create_future()
            loop.call_soon(future.set_result, 0.0)
            return future

        result = await run_parallel_all_async(
            [worker],
            max_attempts=2,
            on_retry=on_retry,
        )

        assert result == ["ok"]
        assert retry_log == [(0, 1, "TimeoutError")]
        assert attempts == 2

    asyncio.run(_run())

