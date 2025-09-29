from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any, TypeVar

from _pytest.recwarn import WarningsRecorder
import pytest
from src.llm_adapter.errors import RateLimitError, TimeoutError
from src.llm_adapter.provider_spi import (
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
)
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner, ParallelAllResult, Runner
from src.llm_adapter.runner_config import (
    BackoffPolicy,
    ConsensusConfig,
    RunnerConfig,
    RunnerMode,
)
from src.llm_adapter.runner_parallel import ParallelExecutionError


class _FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, duration: float) -> None:
        self.current += duration

    async def async_sleep(self, duration: float) -> None:
        self.current += duration


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.events if kind == event_type]


class _AsyncProbeProvider:
    def __init__(
        self,
        name: str,
        *,
        delay: float,
        text: str | None = None,
        failures: list[BaseException] | None = None,
        block: bool = False,
    ) -> None:
        self._name = name
        self._delay = delay
        self._text = text or name
        self.cancelled = False
        self.finished = False
        self.invocations = 0
        self._failures = list(failures or [])
        self._block = block

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
        self.invocations += 1
        try:

            if self._failures:
                raise self._failures.pop(0)
            if self._block:
                await asyncio.Event().wait()
                latency_ms = 0
            elif self._delay <= 0:

                latency_ms = 0
            else:
                await asyncio.sleep(self._delay)
                latency_ms = int(self._delay * 1000)
            return ProviderResponse(
                text=f"{self._text}:{request.prompt}",
                latency_ms=latency_ms,
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished = True


class _StaticProvider:
    def __init__(self, name: str, text: str, latency_ms: int) -> None:
        self._name = name
        self._text = text
        self._latency_ms = latency_ms

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._text,
            latency_ms=self._latency_ms,
            token_usage=TokenUsage(prompt=1, completion=1),
            model=request.model,
            finish_reason="stop",
        )


T = TypeVar("T")


def _run_without_warnings(action: Callable[[], T]) -> T:
    try:
        warns_cm = pytest.warns(None)
    except TypeError:
        warns_cm = WarningsRecorder(_ispytest=True)
    with warns_cm as warnings_record:
        result = action()
    assert len(warnings_record) == 0
    return result


def _patch_runner_sleep(
    monkeypatch: pytest.MonkeyPatch,
    clock: _FakeClock,
    calls: list[float] | None = None,
) -> None:
    async def _fake_sleep(duration: float) -> None:
        if calls is not None:
            calls.append(duration)
        await clock.async_sleep(duration)

    monkeypatch.setattr("src.llm_adapter.runner_async.asyncio.sleep", _fake_sleep)
    monkeypatch.setattr("src.llm_adapter.runner_parallel.asyncio.sleep", _fake_sleep)


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

    asyncio.run(_execute())

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
        async_runner.run_async(async_request, shadow_metrics_path=async_metrics)
    )

    assert async_response.text == sync_response.text
    assert async_response.model == sync_response.model
    assert async_metrics.exists()


def test_async_shadow_exec_uses_injected_logger(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    logger = _CapturingLogger()
    runner = AsyncRunner([primary], logger=logger)

    request = ProviderRequest(prompt="hello", model="primary-model")
    metrics_path = tmp_path / "async-unused.jsonl"

    response = _run_without_warnings(
        lambda: asyncio.run(
            runner.run_async(
                request,
                shadow=shadow,
                shadow_metrics_path=metrics_path,
            )
        )
    )

    diff_events = logger.of_type("shadow_diff")
    assert len(diff_events) == 1
    diff_event = diff_events[0]
    assert diff_event["primary_provider"] == "primary"
    assert diff_event["shadow_provider"] == "shadow"
    assert diff_event["shadow_ok"] is True
    assert diff_event["primary_text_len"] == len(response.text)
    assert not metrics_path.exists()


def test_async_shadow_exec_without_metrics_path_skips_logging() -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    logger = _CapturingLogger()
    runner = AsyncRunner([primary], logger=logger)

    request = ProviderRequest(prompt="hello", model="primary-model")

    asyncio.run(
        runner.run_async(
            request,
            shadow=shadow,
            shadow_metrics_path=None,
        )
    )

    assert logger.of_type("shadow_diff") == []


def test_async_shadow_exec_records_metrics(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    runner = AsyncRunner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    metadata = {"trace_id": "trace-async", "project_id": "proj-async"}
    request = ProviderRequest(prompt="hello", metadata=metadata, model="primary-model")

    response = _run_without_warnings(
        lambda: asyncio.run(
            runner.run_async(
                request,
                shadow=shadow,
                shadow_metrics_path=metrics_path,
            )
        )
    )

    assert response.text.startswith("echo(primary):")
    assert metrics_path.exists()

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")
    call_event = next(item for item in payloads if item["event"] == "provider_call")

    assert diff_event["primary_provider"] == "primary"
    assert diff_event["shadow_provider"] == "shadow"
    assert diff_event["shadow_ok"] is True
    token_usage = response.token_usage
    assert token_usage is not None
    assert diff_event["primary_token_usage_total"] == token_usage.total
    expected_tokens = max(1, len("hello") // 4) + 16
    assert diff_event["shadow_token_usage_total"] == expected_tokens
    assert diff_event["shadow_text_len"] == len("echo(shadow): hello")
    assert diff_event["request_fingerprint"]
    assert call_event["provider"] == "primary"
    assert call_event["shadow_used"] is True
    assert call_event["status"] == "ok"
    assert call_event["latency_ms"] == response.latency_ms
    assert call_event["tokens_in"] == token_usage.prompt
    assert call_event["tokens_out"] == token_usage.completion
    assert call_event["trace_id"] == metadata["trace_id"]
    assert call_event["project_id"] == metadata["project_id"]


def test_async_shadow_error_records_metrics(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = AsyncRunner([primary])

    metrics_path = tmp_path / "metrics-error.jsonl"

    asyncio.run(
        runner.run_async(
            ProviderRequest(prompt="[TIMEOUT] hello", model="primary-model"),
            shadow=shadow,
            shadow_metrics_path=metrics_path,
        )
    )

    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    diff_event = next(item for item in payloads if item["event"] == "shadow_diff")

    assert diff_event["shadow_ok"] is False
    assert diff_event["shadow_error"] == "TimeoutError"
    assert diff_event["shadow_error_message"] == "simulated timeout"
    assert diff_event["shadow_duration_ms"] >= 0


def test_async_consensus_vote_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)

    agree_text = "agree: async"
    agree_a = _StaticProvider("agree_a", agree_text, latency_ms=5)
    agree_b = _StaticProvider("agree_b", agree_text, latency_ms=7)
    disagree = _StaticProvider("disagree", "disagree: async", latency_ms=9)
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers=set())

    runner = AsyncRunner(
        [agree_a, agree_b, disagree],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )

    request = ProviderRequest(prompt="async hello", model="m-async-consensus")
    metrics_path = tmp_path / "async-consensus.jsonl"

    response = asyncio.run(
        runner.run_async(
            request,
            shadow=shadow,
            shadow_metrics_path=metrics_path,
        )
    )

    assert response.text == agree_text
    payloads = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]
    consensus_event = next(
        item for item in payloads if item.get("event") == "consensus_vote"
    )
    assert consensus_event["votes_for"] == 2
    assert consensus_event["votes_against"] == 1
    assert consensus_event["winner_provider"] == "agree_a"

    winner_diff = next(
        item
        for item in payloads
        if item.get("event") == "shadow_diff"
        and item.get("primary_provider") == "agree_a"
    )
    assert winner_diff["shadow_consensus_delta"]["votes_total"] == 3


def test_async_parallel_any_returns_first_completion() -> None:
    slow = _AsyncProbeProvider("slow", delay=0.1, text="slow")
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    runner = AsyncRunner(
        [slow, fast],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="model-parallel-any")

    response = asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.2))

    assert response.text.startswith("fast:")


def test_async_parallel_any_cancellation_waits_for_cleanup() -> None:
    slow = _AsyncProbeProvider("slow", delay=0.2, text="slow")
    fast = _AsyncProbeProvider("fast", delay=0.01, text="fast")
    runner = AsyncRunner(
        [slow, fast],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hi", model="model-parallel-cancel")

    response = asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.3))

    assert response.text.startswith("fast:")
    assert slow.cancelled is True
    assert slow.finished is True


def test_async_parallel_any_rate_limit_does_not_retry() -> None:
    providers = [
        _AsyncProbeProvider("rl_a", delay=0.0, failures=[RateLimitError("a")]),
        _AsyncProbeProvider("rl_b", delay=0.0),
    ]
    logger = _CapturingLogger()
    runner = AsyncRunner(
        providers,
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="rl", model="model-parallel-any-rl")

    async def _execute() -> ProviderResponse:
        return await runner.run_async(request)

    response = asyncio.run(asyncio.wait_for(_execute(), timeout=0.2))

    assert response.text == "rl_b:rl"
    assert [provider.invocations for provider in providers] == [1, 1]
    retries = logger.of_type("retry")
    assert all(record["error_type"] != "RateLimitError" for record in retries)


def test_async_consensus_quorum_failure() -> None:
    provider_a = _AsyncProbeProvider("pa", delay=0.01, text="A")
    provider_b = _AsyncProbeProvider("pb", delay=0.01, text="B")
    runner = AsyncRunner(
        [provider_a, provider_b],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            consensus=ConsensusConfig(quorum=2),
        ),
    )
    request = ProviderRequest(prompt="topic", model="model-consensus")

    with pytest.raises(ParallelExecutionError):
        asyncio.run(runner.run_async(request))


def test_async_consensus_failure_details() -> None:
    timeout_provider = _AsyncProbeProvider(
        "timeout",
        delay=0.0,
        failures=[TimeoutError("simulated timeout")],
    )
    rate_provider = _AsyncProbeProvider(
        "rate",
        delay=0.0,
        failures=[RateLimitError("simulated rate limit")],
    )
    runner = AsyncRunner(
        [timeout_provider, rate_provider],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=2,
            max_attempts=2,
            backoff=BackoffPolicy(
                rate_limit_sleep_s=0.0,
                timeout_next_provider=False,
                retryable_next_provider=False,
            ),
        ),
    )
    request = ProviderRequest(prompt="consensus", model="consensus-failure")

    with pytest.raises(ParallelExecutionError) as exc_info:
        asyncio.run(runner.run_async(request))

    error = exc_info.value
    failures = error.failures if hasattr(error, "failures") else None
    expected = [
        {
            "provider": "timeout",
            "attempt": "1",
            "summary": "TimeoutError: simulated timeout",
        },
        {
            "provider": "rate",
            "attempt": "2",
            "summary": "RateLimitError: simulated rate limit",
        },
    ]
    assert failures == expected
    message = str(error)
    for detail in expected:
        assert detail["provider"] in message
        assert detail["attempt"] in message
        assert detail["summary"] in message


def test_async_consensus_error_details() -> None:
    test_async_consensus_failure_details()


def test_async_parallel_retry_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    request_any = ProviderRequest(prompt="retry", model="parallel-any")
    clock_any = _FakeClock()
    sleep_calls: list[float] = []
    _patch_runner_sleep(monkeypatch, clock_any, sleep_calls)

    flaky = _AsyncProbeProvider(
        "primary",
        delay=0.0,
        text="ok",
        failures=[RateLimitError("slow"), TimeoutError("later")],
    )
    blocker = _AsyncProbeProvider("secondary", delay=0.0, block=True)
    logger = _CapturingLogger()
    runner_any = AsyncRunner(
        [flaky, blocker],
        logger=logger,
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.25, timeout_next_provider=False),
        ),
    )

    response = asyncio.run(
        asyncio.wait_for(
            runner_any.run_async(request_any, shadow_metrics_path="unused.jsonl"),
            timeout=1,
        )
    )
    assert response.text == "ok:retry"
    assert (
        flaky.invocations,
        flaky.cancelled,
        flaky.finished,
        blocker.cancelled,
        blocker.finished,
    ) == (3, False, True, True, True)
    assert [event["error_type"] for event in logger.of_type("retry")] == [
        "RateLimitError",
        "TimeoutError",
    ]

    flaky_fail = _AsyncProbeProvider(
        "limited",
        delay=0.0,
        text="never",
        failures=[RateLimitError("first"), RateLimitError("second"), RateLimitError("third")],
    )
    runner_fail = AsyncRunner(
        [flaky_fail],
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.1),
            max_attempts=2,
        ),
    )

    with pytest.raises(ParallelExecutionError):
        asyncio.run(
            asyncio.wait_for(
                runner_fail.run_async(request_any, shadow_metrics_path="unused.jsonl"),
                timeout=1,
            )
        )

    assert (
        flaky_fail.invocations,
        flaky_fail.cancelled,
        flaky_fail.finished,
    ) == (2, False, True)
    assert sleep_calls == [0.25, 0.1]

    request_all = ProviderRequest(prompt="gather", model="parallel-all")
    _patch_runner_sleep(monkeypatch, _FakeClock())
    fast = _AsyncProbeProvider("fast", delay=0.0, text="fast")
    slow = _AsyncProbeProvider("slow", delay=0.1, text="slow")
    ready = _AsyncProbeProvider("ready", delay=0.0, text="ready")
    logger_all = _CapturingLogger()
    runner_all = AsyncRunner(
        [fast, slow, ready],
        logger=logger_all,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL),
    )

    result = asyncio.run(runner_all.run_async(request_all, shadow_metrics_path="unused.jsonl"))
    assert isinstance(result, ParallelAllResult)
    assert [entry[1].name() for entry in result.invocations] == ["fast", "slow", "ready"]
    assert result.primary_response.text == "fast:gather"
    assert [(p.cancelled, p.finished) for p in (fast, slow, ready)] == [(False, True)] * 3
    assert logger_all.of_type("retry") == []


def test_async_parallel_all_rate_limit_retries() -> None:
    providers = [
        _AsyncProbeProvider("rl_all_a", delay=0.0, failures=[RateLimitError("a")]),
        _AsyncProbeProvider("rl_all_b", delay=0.0, failures=[RateLimitError("b")]),
    ]
    logger = _CapturingLogger()
    runner = AsyncRunner(
        providers,
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL, max_concurrency=2),
    )
    request = ProviderRequest(prompt="rl-all", model="model-parallel-all-rl")

    async def _execute() -> ParallelAllResult[Any, ProviderResponse]:
        return await runner.run_async(request)

    result = asyncio.run(asyncio.wait_for(_execute(), timeout=0.2))

    assert [response.text for response in result.responses] == [
        f"{provider.name()}:{request.prompt}" for provider in providers
    ]
    assert [provider.invocations for provider in providers] == [2, 2]
    retries = logger.of_type("retry")
    assert len(retries) == 2
    assert all(record["error_type"] == "RateLimitError" for record in retries)
    assert {record["next_attempt"] for record in retries} == {3, 4}
