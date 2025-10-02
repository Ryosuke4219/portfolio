from __future__ import annotations

import asyncio
from collections.abc import Sequence
from concurrent.futures import CancelledError, Future
import json
from pathlib import Path
import threading
import time
from typing import Any, cast

import pytest

from src.llm_adapter.errors import RateLimitError, TimeoutError
from src.llm_adapter.parallel_exec import (
    ParallelExecutionError,
    run_parallel_all_async,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from src.llm_adapter.provider_spi import (
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
    TokenUsage,
)
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner, ParallelAllResult
from src.llm_adapter.runner_config import BackoffPolicy, RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import (
    _normalize_candidate_text,
    compute_consensus,
    ConsensusConfig,
)
from src.llm_adapter.runner_sync import Runner
from src.llm_adapter.runner_sync_invocation import (
    CancelledResultsBuilder,
    ParallelResultLogger,
    ProviderInvocationResult,
)
from src.llm_adapter.shadow import run_with_shadow

from .parallel_helpers import (
    _install_recording_executor,
    _read_metrics,
    _RetryProbeProvider,
    _StaticProvider,
    _worker_for,
    RecordingLogger,
)


def test_run_parallel_any_sync_cancels_pending_futures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_recording_executor(monkeypatch)
    assert created == []

    cancelled_futures: set[Future[Any]] = set()
    original_cancel = Future.cancel

    def _tracking_cancel(self: Future[Any]) -> bool:
        cancelled_futures.add(self)
        return original_cancel(self)

    monkeypatch.setattr(Future, "cancel", _tracking_cancel, raising=False)

    slow_gate = threading.Event()

    def _slow_worker(name: str) -> str:
        slow_gate.wait(timeout=0.25)
        return name

    def _fast_worker() -> str:
        return "fast"

    cancelled_indices: list[Sequence[int]] = []

    result = run_parallel_any_sync(
        (
            lambda: _slow_worker("slow-1"),
            _fast_worker,
            lambda: _slow_worker("slow-2"),
        ),
        on_cancelled=lambda indices: cancelled_indices.append(tuple(indices)),
    )

    assert result == "fast"
    assert cancelled_indices == [tuple(sorted((0, 2)))]
    assert len(created) == 1
    executor = created[0]
    assert len(executor.submitted) == 3
    assert executor.submitted[0] in cancelled_futures
    assert executor.submitted[1] not in cancelled_futures
    assert executor.submitted[2] in cancelled_futures

    slow_gate.set()


def test_runner_parallel_any_records_failures() -> None:
    provider_a = _RetryProbeProvider(
        "fail-a",
        [TimeoutError("primary timeout")],
    )
    provider_b = _RetryProbeProvider(
        "fail-b",
        [RateLimitError("secondary limit")],
    )
    runner = Runner(
        [provider_a, provider_b],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY),
    )
    request = ProviderRequest(prompt="fail", model="parallel-any-fail")

    with pytest.raises(ParallelExecutionError) as excinfo:
        runner.run(request, shadow=None)

    failures = excinfo.value.failures
    assert failures is not None
    assert failures == [
        {
            "provider": "fail-a",
            "attempt": "1",
            "summary": "TimeoutError: primary timeout",
        },
        {
            "provider": "fail-b",
            "attempt": "2",
            "summary": "RateLimitError: secondary limit",
        },
    ]


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


def test_parallel_result_logger_marks_cancelled_results_ok() -> None:
    provider = _StaticProvider("cancelled", text="unused", latency_ms=5)
    request = ProviderRequest(prompt="hello", model="m")
    request_fingerprint = "fingerprint"
    run_started = 0.0

    provider_call_log: list[dict[str, object]] = []
    run_metric_log: list[dict[str, object]] = []

    logger = ParallelResultLogger(
        log_provider_call=lambda event_logger, **record: provider_call_log.append(record),
        log_run_metric=lambda event_logger, **record: run_metric_log.append(record),
        estimate_cost=lambda provider, tokens_in, tokens_out: 0.0,
        elapsed_ms=lambda _: 42,
    )

    cancelled_result = ProviderInvocationResult(
        provider=provider,
        attempt=1,
        total_providers=2,
        response=None,
        error=CancelledError(),
        latency_ms=None,
        tokens_in=None,
        tokens_out=None,
        shadow_metrics=None,
        shadow_metrics_extra=None,
        provider_call_logged=False,
    )

    logger.log_results(
        [cancelled_result],
        event_logger=None,
        request=request,
        request_fingerprint=request_fingerprint,
        metadata={},
        run_started=run_started,
        shadow_used=False,
    )

    assert len(provider_call_log) == 1
    assert provider_call_log[0]["status"] == "ok"
    assert provider_call_log[0]["latency_ms"] == 42
    assert provider_call_log[0]["error"] is None

    assert len(run_metric_log) == 1
    assert run_metric_log[0]["status"] == "ok"
    assert run_metric_log[0]["error"] is None
    assert run_metric_log[0]["latency_ms"] == 42


def test_parallel_primitives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)
    failing = MockProvider("fail", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    fast = MockProvider("fast", base_latency_ms=1, error_markers=set())
    fail_request = ProviderRequest(prompt="[TIMEOUT] hi", model="m1")
    ok_request = ProviderRequest(prompt="hi", model="m2")
    winner = run_parallel_any_sync(
        (
            lambda: failing.invoke(fail_request),
            lambda: fast.invoke(ok_request),
        )
    )
    assert winner.text.startswith("echo(fast):")
    request = ProviderRequest(prompt="hello", model="m")
    providers = [
        MockProvider("p1", base_latency_ms=1, error_markers=set()),
        MockProvider("p2", base_latency_ms=2, error_markers=set()),
    ]
    collected = run_parallel_all_sync(
        tuple(_worker_for(provider, request) for provider in providers)
    )
    assert [res.text for res in collected] == ["echo(p1): hello", "echo(p2): hello"]
    responses = [
        ProviderResponse("A", 0),
        ProviderResponse("A", 0),
        ProviderResponse("B", 0),
    ]
    result = compute_consensus(responses, config=ConsensusConfig(quorum=2))
    assert result.response.text == "A"
    assert result.votes == 2
    with pytest.raises(ParallelExecutionError):
        compute_consensus(responses, config=ConsensusConfig(quorum=3))


def test_compute_consensus_accepts_numeric_scores() -> None:
    responses = [
        ProviderResponse(text="int", latency_ms=0, raw={"score": 1}),
        ProviderResponse(text="float", latency_ms=0, raw={"score": 1.5}),
    ]

    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="weighted", quorum=1),
    )

    assert result.response.text == "float"
    assert result.scores == {"int": 1.0, "float": 1.5}


def test_compute_consensus_records_schema_failures_and_applies_tie_breaker() -> None:
    schema = json.dumps({"type": "object", "required": ["answer"]})
    responses = [
        ProviderResponse(
            text=json.dumps({"answer": "slow"}),
            latency_ms=20,
        ),
        ProviderResponse(
            text=json.dumps({"answer": "fast"}),
            latency_ms=10,
        ),
        ProviderResponse(text="oops", latency_ms=1),
    ]

    result = compute_consensus(
        responses,
        config=ConsensusConfig(schema=schema, tie_breaker="latency", quorum=1),
    )

    assert result.response.text == json.dumps({"answer": "fast"})
    assert result.tie_break_applied is True
    assert result.tie_breaker_selected == "latency"
    assert result.tie_break_reason == "latency(min=10)"
    assert result.abstained == 1
    assert result.schema_checked is True
    assert result.schema_failures == {2: "invalid json: Expecting value"}


def test_normalize_candidate_text_for_strings() -> None:
    normalized_a, display_a = _normalize_candidate_text(" Foo   Bar ")
    normalized_b, display_b = _normalize_candidate_text("foo bar")
    normalized_c, _ = _normalize_candidate_text("Foo baz")

    assert normalized_a == normalized_b
    assert normalized_a != normalized_c
    assert display_a == "Foo   Bar"
    assert display_b == "foo bar"


def test_normalize_candidate_text_for_json_payloads() -> None:
    normalized_a, _ = _normalize_candidate_text('{"b":[2,3],"a":1}')
    normalized_b, display_b = _normalize_candidate_text('{ "a" : 1, "b" : [2,3] }')
    normalized_c, _ = _normalize_candidate_text('{"a":2,"b":[2,3]}')

    assert normalized_a == normalized_b
    assert normalized_a != normalized_c
    assert display_b == '{ "a" : 1, "b" : [2,3] }'


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


def test_parallel_any_with_shadow_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)
    failing = MockProvider("fail", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    primary = MockProvider("primary", base_latency_ms=1, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers={"[TIMEOUT]"})
    fail_request = ProviderRequest(prompt="[TIMEOUT] fail", model="m")
    success_request = ProviderRequest(prompt="[TIMEOUT] ok", model="m")
    metrics_path = tmp_path / "parallel.jsonl"

    def fail_worker() -> ProviderResponse:
        return failing.invoke(fail_request)

    def success_worker() -> ProviderResponse:
        result = run_with_shadow(
            primary,
            shadow,
            success_request,
            metrics_path=metrics_path,
        )
        if isinstance(result, tuple):
            return result[0]
        return cast(ProviderResponse, result)

    response = run_parallel_any_sync((fail_worker, success_worker))
    assert response.text.startswith("echo(primary):")
    payloads = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]
    shadow_event = next(item for item in payloads if item["event"] == "shadow_diff")
    assert shadow_event["shadow_provider"] == "shadow"
    assert shadow_event["shadow_ok"] is False
    assert shadow_event["shadow_error"] == "TimeoutError"


def test_runner_parallel_any_returns_success_after_fast_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingProvider:
        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            raise TimeoutError("fast failure")

    class _SlowProvider(_StaticProvider):
        def __init__(self, name: str, text: str, latency_ms: int, delay: float) -> None:
            super().__init__(name, text, latency_ms)
            self._delay = delay

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            time.sleep(self._delay)
            return super().invoke(request)

    providers: list[ProviderSPI] = [
        _FailingProvider("fail-fast"),
        _SlowProvider("slow-success", "slow-ok", latency_ms=5, delay=0.05),
    ]
    cost_calls: list[tuple[object, int, int]] = []

    def _record_cost(provider: object, tokens_in: int, tokens_out: int) -> float:
        cost_calls.append((provider, tokens_in, tokens_out))
        return 0.0

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync.estimate_cost", _record_cost, raising=False
    )
    logger = RecordingLogger()
    runner = Runner(
        providers,
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=1),
    )
    request = ProviderRequest(prompt="hello", model="m-parallel-any")

    response = runner.run(request)

    assert response.text == "slow-ok"
    run_metric_events = [
        event for event in logger.of_type("run_metric") if event["status"] == "ok"
    ]
    assert len(run_metric_events) == 1
    assert run_metric_events[0]["attempts"] == 2
    assert len(cost_calls) == 1
    cost_provider, cost_tokens_in, cost_tokens_out = cost_calls[0]
    assert cost_provider is providers[1]
    assert (cost_tokens_in, cost_tokens_out) == (1, 1)


def test_runner_parallel_any_logs_cancelled_providers() -> None:
    class _SlowProvider(_StaticProvider):
        def __init__(self, name: str, text: str, latency_ms: int, delay: float) -> None:
            super().__init__(name, text, latency_ms)
            self._delay = delay

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            time.sleep(self._delay)
            return super().invoke(request)

    fast = _StaticProvider("fast", "fast-ok", latency_ms=1)
    slow = _SlowProvider("slow", "slow-ok", latency_ms=10, delay=0.1)
    logger = RecordingLogger()
    runner = Runner(
        [fast, slow],
        logger=logger,
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=2),
    )
    request = ProviderRequest(prompt="hello", model="parallel-any-cancel")

    response = runner.run(request)

    assert response.text == "fast-ok"
    provider_calls = {
        event["provider"]: event for event in logger.of_type("provider_call")
    }
    assert provider_calls["fast"]["status"] == "ok"
    assert provider_calls["slow"]["status"] == "ok"
    assert provider_calls["slow"].get("error_type") in (None, "CancelledError")
    run_metrics = {
        event["provider"]: event
        for event in logger.of_type("run_metric")
        if event["provider"] is not None
    }
    assert run_metrics["fast"]["status"] == "ok"
    assert run_metrics["slow"]["status"] == "ok"
    assert run_metrics["slow"].get("error_type") is None


def test_runner_parallel_any_retries_until_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda delay: sleep_calls.append(delay))
    executors = _install_recording_executor(monkeypatch)
    provider = _RetryProbeProvider(
        "retry-any",
        [RateLimitError("retry"), "final"],
        latency_s=0.001,
    )
    runner = Runner(
        [provider, provider, provider],
        config=RunnerConfig(
            mode=RunnerMode.PARALLEL_ANY,
            max_concurrency=1,
            max_attempts=2,
            backoff=BackoffPolicy(rate_limit_sleep_s=0.05),
        ),
    )
    request = ProviderRequest(prompt="retry", model="parallel-any-retry")
    metrics_path = tmp_path / "parallel_any_retry.jsonl"

    response = runner.run(request, shadow=None, shadow_metrics_path=metrics_path)

    assert response.text.endswith("final")
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
    assert provider_calls[0]["status"] == "error"
    assert provider_calls[0]["error_type"] == "RateLimitError"
    assert provider_calls[1]["status"] == "ok"
    run_metrics = [
        event
        for event in events
        if event["event"] == "run_metric" and event["status"] == "ok"
    ]
    assert len(run_metrics) == 1
    assert run_metrics[0]["attempts"] == 2


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


def test_consensus_vote_event_and_shadow_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.random.random", lambda: 0.0)

    agree_text = "agree: hello"
    agree_a = _StaticProvider("agree_a", agree_text, latency_ms=5)
    agree_b = _StaticProvider("agree_b", agree_text, latency_ms=7)
    disagree = _StaticProvider("disagree", "disagree: hello", latency_ms=9)
    shadow = MockProvider("shadow", base_latency_ms=1, error_markers=set())

    runner = Runner(
        [agree_a, agree_b, disagree],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )

    request = ProviderRequest(prompt="hello", model="m-consensus")
    metrics_path = tmp_path / "consensus.jsonl"

    response = runner.run(
        request,
        shadow=shadow,
        shadow_metrics_path=metrics_path,
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
    assert consensus_event["strategy"] == "majority_vote"
    assert consensus_event["voters_total"] == 3
    assert consensus_event["votes_for"] == 2
    assert consensus_event["votes_against"] == 1
    assert consensus_event["winner_provider"] == "agree_a"
    assert consensus_event["winner_latency_ms"] == response.latency_ms
    assert consensus_event["votes"][response.text] == 2
    summaries = consensus_event["candidate_summaries"]
    assert {entry["provider"] for entry in summaries} == {
        "agree_a",
        "agree_b",
        "disagree",
    }

    run_metric_events = {
        item["provider"]: item["latency_ms"]
        for item in payloads
        if item.get("event") == "run_metric" and item.get("provider") is not None
    }
    expected_latencies = {
        agree_a.name(): agree_a.latency_ms,
        agree_b.name(): agree_b.latency_ms,
        disagree.name(): disagree.latency_ms,
    }
    assert run_metric_events == expected_latencies

    winner_diff = next(
        item
        for item in payloads
        if item.get("event") == "shadow_diff"
        and item.get("primary_provider") == "agree_a"
    )
    assert winner_diff["shadow_consensus_delta"]["votes_for"] == 2
    assert winner_diff["shadow_consensus_delta"]["votes_total"] == 3
