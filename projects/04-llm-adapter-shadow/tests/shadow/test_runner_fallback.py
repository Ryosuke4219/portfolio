from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from src.llm_adapter.errors import ProviderSkip, RateLimitError, RetriableError, TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner import BackoffPolicy, Runner, RunnerConfig


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class _ErrorProvider(ProviderSPI):
    def __init__(self, name: str, exc: Exception) -> None:
        self._name = name
        self._exc = exc

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        raise self._exc


class _SuccessProvider(ProviderSPI):
    def __init__(
        self,
        name: str,
        *,
        tokens_in: int = 12,
        tokens_out: int = 8,
        latency_ms: int = 5,
        cost_usd: float = 0.123,
    ) -> None:
        self._name = name
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._latency = latency_ms
        self._cost = cost_usd
        self.cost_calls: list[tuple[int, int]] = []

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=f"{self._name}:ok",
            latency_ms=self._latency,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            model=request.model,
        )

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        self.cost_calls.append((tokens_in, tokens_out))
        return self._cost


def _run_and_collect(
    providers: Iterable[ProviderSPI],
    *,
    metrics_path: Path,
    prompt: str = "hello",
    config: RunnerConfig | None = None,
) -> tuple[ProviderResponse, list[dict[str, Any]]]:
    runner = Runner(list(providers), config=config)
    request = ProviderRequest(prompt=prompt, model="demo-model")
    response = runner.run(request, shadow_metrics_path=metrics_path)
    return response, _read_metrics(metrics_path)


def test_first_failure_then_success_records_chain(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    failing = _ErrorProvider("fail-first", RetriableError("transient"))
    succeeding = _SuccessProvider("success")

    _, records = _run_and_collect([failing, succeeding], metrics_path=metrics_path)

    provider_events = [rec for rec in records if rec["event"] == "provider_call"]
    assert [event["provider"] for event in provider_events] == ["fail-first", "success"]
    assert provider_events[0]["status"] == "error"
    assert provider_events[1]["status"] == "ok"

    run_event = next(rec for rec in records if rec["event"] == "run_metric")
    assert run_event["status"] == "ok"
    assert run_event["provider"] == "success"
    assert run_event["attempts"] == 2


def test_rate_limit_triggers_backoff_and_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    rate_limited = _ErrorProvider("rate-limit", RateLimitError("slow down"))
    succeeding = _SuccessProvider("success")

    sleep_calls: list[float] = []

    def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.llm_adapter.runner.time.sleep", _fake_sleep)

    config = RunnerConfig(backoff=BackoffPolicy(rate_limit_seconds=0.12))
    _, records = _run_and_collect(
        [rate_limited, succeeding], metrics_path=metrics_path, config=config
    )

    assert sleep_calls == [0.12]
    first_call = next(
        rec
        for rec in records
        if rec["event"] == "provider_call" and rec["provider"] == "rate-limit"
    )
    assert first_call["status"] == "error"
    assert first_call["error_type"] == "RateLimitError"


def test_timeout_switches_to_next_provider(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    timeouting = _ErrorProvider("slow", TimeoutError("too slow"))
    succeeding = _SuccessProvider("success")

    _, records = _run_and_collect([timeouting, succeeding], metrics_path=metrics_path)

    timeout_event = next(
        rec
        for rec in records
        if rec["event"] == "provider_call" and rec["provider"] == "slow"
    )
    assert timeout_event["status"] == "error"
    assert timeout_event["error_type"] == "TimeoutError"

    success_event = next(
        rec
        for rec in records
        if rec["event"] == "provider_call" and rec["provider"] == "success"
    )
    assert success_event["status"] == "ok"


def test_run_metric_contains_tokens_and_cost(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    succeeding = _SuccessProvider("success", tokens_in=21, tokens_out=9, cost_usd=0.456)

    _, records = _run_and_collect([succeeding], metrics_path=metrics_path)

    run_event = next(rec for rec in records if rec["event"] == "run_metric")
    assert run_event["tokens_in"] == 21
    assert run_event["tokens_out"] == 9
    assert run_event["cost_usd"] == pytest.approx(0.456)
    assert succeeding.cost_calls == [(21, 9)]


class _CountingProvider(_SuccessProvider):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.calls = 0

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return super().invoke(request)


def test_max_attempts_limits_iteration(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    failing = _ErrorProvider("failing", RetriableError("boom"))
    skipped = _ErrorProvider("skipped", ProviderSkip("skip"))
    untouched = _CountingProvider("untouched")

    runner = Runner(
        [failing, skipped, untouched], config=RunnerConfig(max_attempts=1)
    )
    request = ProviderRequest(prompt="hi", model="demo-model")

    with pytest.raises(RetriableError):
        runner.run(request, shadow_metrics_path=metrics_path)

    assert untouched.calls == 0
