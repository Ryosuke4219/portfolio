from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import time

import pytest
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from src.llm_adapter.runner_config import ConsensusConfig, RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import ParallelExecutionError
from src.llm_adapter.runner_sync import Runner


class _ExternalRunnerMode(Enum):
    PARALLEL_ANY = "parallel_any"


def test_runner_config_accepts_string_mode() -> None:
    config = RunnerConfig(mode="parallel_any")

    assert config.mode is RunnerMode.PARALLEL_ANY


def test_runner_config_accepts_foreign_enum() -> None:
    config = RunnerConfig(mode=_ExternalRunnerMode.PARALLEL_ANY)

    assert config.mode is RunnerMode.PARALLEL_ANY


class _FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, duration: float) -> None:
        self.current += duration


class _MockProvider:
    def __init__(self, name: str, behavior: Callable[[ProviderRequest], ProviderResponse]):
        self._name = name
        self._behavior = behavior
        self.calls = 0

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return self._behavior(request)


def _response(text: str) -> ProviderResponse:
    return ProviderResponse(text=text, latency_ms=10, tokens_in=5, tokens_out=3)


def test_runner_parallel_any_cancels_pending_workers() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hi")

    fast = _MockProvider("fast", lambda _: _response("fast"))

    def _slow(_: ProviderRequest) -> ProviderResponse:
        time.sleep(0.05)
        return _response("slow")

    slow = _MockProvider("slow", _slow)

    def _never(_: ProviderRequest) -> ProviderResponse:
        raise AssertionError("should not be called")

    blocked = _MockProvider("blocked", _never)

    runner = Runner(
        [fast, slow, blocked],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ANY, max_concurrency=1),
    )

    started = time.time()
    result = runner.run(request)
    elapsed = time.time() - started

    assert result.text == "fast"
    assert fast.calls == 1
    assert elapsed < 0.04
    # third provider should never run due to early cancellation
    assert blocked.calls == 0


def test_runner_parallel_all_collects_all_results() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hi")

    provider_a = _MockProvider("a", lambda _: _response("A"))
    provider_b = _MockProvider("b", lambda _: _response("B"))

    runner = Runner(
        [provider_a, provider_b],
        config=RunnerConfig(mode=RunnerMode.PARALLEL_ALL, max_concurrency=2),
    )

    result = runner.run(request)

    assert result.text == "A"
    assert provider_a.calls == 1
    assert provider_b.calls == 1


def test_runner_consensus_majority_selection() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hi")

    agree1 = _MockProvider("agree-1", lambda _: _response("agree"))
    agree2 = _MockProvider("agree-2", lambda _: _response("agree"))
    disagree = _MockProvider("disagree", lambda _: _response("disagree"))

    runner = Runner(
        [agree1, agree2, disagree],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )

    result = runner.run(request)

    assert result.text == "agree"


def test_runner_consensus_quorum_failure() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hi")

    agree = _MockProvider("agree", lambda _: _response("agree"))
    disagree = _MockProvider("disagree", lambda _: _response("disagree"))
    abstain = _MockProvider("abstain", lambda _: _response("abstain"))

    runner = Runner(
        [agree, disagree, abstain],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=2,
            consensus=ConsensusConfig(quorum=3),
        ),
    )

    with pytest.raises(ParallelExecutionError):
        runner.run(request)


def test_runner_sequential_enforces_rpm(monkeypatch: pytest.MonkeyPatch) -> None:
    request = ProviderRequest(model="gpt-test", prompt="hi")
    clock = _FakeClock()
    monkeypatch.setattr("src.llm_adapter.runner_shared.time.monotonic", clock.monotonic)
    monkeypatch.setattr("src.llm_adapter.runner_shared.time.sleep", clock.sleep)

    call_times: list[float] = []

    def _record(_: ProviderRequest) -> ProviderResponse:
        call_times.append(clock.monotonic())
        return _response("ok")

    provider = _MockProvider("timed", _record)
    runner = Runner([provider], config=RunnerConfig(rpm=30))

    runner.run(request)
    runner.run(request)

    assert call_times[1] - call_times[0] >= 2.0
