from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner_parallel import (
    ConsensusConfig,
    ParallelExecutionError,
    compute_consensus,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from src.llm_adapter.shadow import run_with_shadow


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
    collected = run_parallel_all_sync(tuple(lambda p=p: p.invoke(request) for p in providers))
    assert [res.text for res in collected] == ["echo(p1): hello", "echo(p2): hello"]
    responses = [ProviderResponse("A", 0), ProviderResponse("A", 0), ProviderResponse("B", 0)]
    result = compute_consensus(responses, config=ConsensusConfig(quorum=2))
    assert result.response.text == "A"
    assert result.votes == 2
    with pytest.raises(ParallelExecutionError):
        compute_consensus(responses, config=ConsensusConfig(quorum=3))


def test_parallel_any_with_shadow_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        return run_with_shadow(
            primary,
            shadow,
            success_request,
            metrics_path=metrics_path,
        )

    response = run_parallel_any_sync((fail_worker, success_worker))
    assert response.text.startswith("echo(primary):")
    payloads = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    shadow_event = next(item for item in payloads if item["event"] == "shadow_diff")
    assert shadow_event["shadow_provider"] == "shadow"
    assert shadow_event["shadow_ok"] is False
    assert shadow_event["shadow_error"] == "TimeoutError"
