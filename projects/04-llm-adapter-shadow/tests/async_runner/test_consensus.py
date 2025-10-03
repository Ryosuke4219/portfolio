from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.llm_adapter.errors import RateLimitError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner import AsyncRunner
from src.llm_adapter.runner_config import (
    BackoffPolicy,
    ConsensusConfig,
    RunnerConfig,
    RunnerMode,
)

from .conftest import _AsyncProbeProvider, _StaticProvider


class _CostProbeProvider(_AsyncProbeProvider):
    def __init__(self, name: str, *, cost: float, text: str) -> None:
        super().__init__(name, delay=0.0, text=text)
        self._cost = cost

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:  # noqa: ARG002
        return self._cost


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
        asyncio.wait_for(
            runner.run_async(
                request,
                shadow=shadow,
                shadow_metrics_path=metrics_path,
            ),
            timeout=0.5,
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
    assert consensus_event["quorum"] == 2
    assert consensus_event["chosen_provider"] == "agree_a"
    assert consensus_event["reason"] == "majority_vote quorum=2/3"

    winner_diff = next(
        item
        for item in payloads
        if item.get("event") == "shadow_diff"
        and item.get("primary_provider") == "agree_a"
    )
    assert winner_diff["shadow_consensus_delta"]["votes_total"] == 3
    assert (
        winner_diff["shadow_consensus_delta"]["reason"]
        == "majority_vote quorum=2/3"
    )


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
        asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.2))


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
        asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.2))

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


def test_async_consensus_timeout_error_is_not_re_raised() -> None:
    agree_a = _AsyncProbeProvider("agree_a", delay=0.0, text="agree")
    agree_b = _AsyncProbeProvider("agree_b", delay=0.0, text="agree")
    timeout_provider = _AsyncProbeProvider(
        "timeout",
        delay=0.0,
        text="timeout",
        failures=[TimeoutError("too slow")],
    )
    runner = AsyncRunner(
        [agree_a, agree_b, timeout_provider],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )
    request = ProviderRequest(prompt="topic", model="model-consensus")

    response = asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.2))

    assert response.text.startswith("agree")


def test_async_consensus_cost_constraints() -> None:
    provider_a = _CostProbeProvider("expensive_a", cost=2.0, text="match")
    provider_b = _CostProbeProvider("expensive_b", cost=3.5, text="match")
    runner = AsyncRunner(
        [provider_a, provider_b],
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=2,
            consensus=ConsensusConfig(quorum=1, max_cost_usd=0.5),
        ),
    )
    request = ProviderRequest(prompt="topic", model="model-consensus-cost")

    with pytest.raises(ParallelExecutionError) as exc_info:
        asyncio.run(asyncio.wait_for(runner.run_async(request), timeout=0.2))

    error = exc_info.value
    failures = error.failures if hasattr(error, "failures") else None
    assert failures is not None
    assert len(failures) == 2
    for item in failures:
        assert "cost" in item.get("summary", "")
