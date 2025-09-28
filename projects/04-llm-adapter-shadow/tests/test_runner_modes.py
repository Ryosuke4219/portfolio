from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import pytest
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from src.llm_adapter.runner_async import AsyncRunner
from src.llm_adapter.runner_config import ConsensusConfig, RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import ParallelExecutionError
from src.llm_adapter.runner_sync import Runner


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


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration

    async def sleep_async(self, duration: float) -> None:
        self.value += duration


def _install_fake_rate_limiter(monkeypatch: pytest.MonkeyPatch, clock: _FakeClock) -> None:
    from src.llm_adapter import runner_shared

    def _factory(rpm: int | None) -> runner_shared.TokenBucketRateLimiter | None:
        if rpm is None or rpm <= 0:
            return None
        return runner_shared.TokenBucketRateLimiter(
            rpm,
            clock=clock.monotonic,
            sleep=clock.sleep,
            async_sleep=clock.sleep_async,
        )

    monkeypatch.setattr(runner_shared, "create_rate_limiter", _factory)
    from src.llm_adapter import runner_async as runner_async_mod
    from src.llm_adapter import runner_sync as runner_sync_mod

    monkeypatch.setattr(runner_async_mod, "create_rate_limiter", _factory)
    monkeypatch.setattr(runner_sync_mod, "create_rate_limiter", _factory)


@pytest.mark.parametrize("async_mode", [False, True])
def test_runner_respects_rpm(monkeypatch: pytest.MonkeyPatch, async_mode: bool) -> None:
    clock = _FakeClock()
    _install_fake_rate_limiter(monkeypatch, clock)

    request = ProviderRequest(model="gpt-test", prompt="hi")
    call_times: list[float] = []

    def _provider(_: ProviderRequest) -> ProviderResponse:
        call_times.append(clock.monotonic())
        return _response("ok")

    if async_mode:
        class _AsyncProvider(_MockProvider):
            async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
                return _provider(request)

        provider = _AsyncProvider("limited", _provider)
        runner = AsyncRunner([provider], config=RunnerConfig(rpm=2))

        async def _run() -> None:
            await runner.run_async(request)
            await runner.run_async(request)

        asyncio.run(_run())
    else:
        provider = _MockProvider("limited", _provider)
        runner = Runner([provider], config=RunnerConfig(rpm=2))
        runner.run(request)
        runner.run(request)

    assert len(call_times) == 2
    assert call_times[0] == pytest.approx(0.0)
    assert call_times[1] == pytest.approx(30.0, abs=1e-6)
