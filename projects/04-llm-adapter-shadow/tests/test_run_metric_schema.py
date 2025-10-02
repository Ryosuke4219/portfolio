from __future__ import annotations

from pathlib import Path

import pytest

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner import Runner, RunnerConfig
from src.llm_adapter.runner_config import RunnerMode

from .shadow._runner_test_helpers import _SuccessProvider, FakeLogger


def _run_and_fetch_event(
    runner: Runner,
    request: ProviderRequest,
    *,
    metrics_path: Path,
) -> list[dict[str, object]]:
    runner.run(request, shadow_metrics_path=metrics_path)
    logger = runner._logger
    assert isinstance(logger, FakeLogger)
    events = logger.of_type("run_metric")
    assert events, "expected at least one run_metric event"
    return events


def test_run_metric_includes_token_usage(tmp_path: Path) -> None:
    provider = _SuccessProvider("primary")
    logger = FakeLogger()
    runner = Runner([provider], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-token-usage")

    events = _run_and_fetch_event(runner, request, metrics_path=tmp_path / "usage.jsonl")
    event = events[0]

    token_usage = event.get("token_usage")
    assert isinstance(token_usage, dict)
    assert set(token_usage) == {"prompt", "completion", "total"}
    for key in ("prompt", "completion", "total"):
        value = token_usage[key]
        assert isinstance(value, int)


def test_sequential_run_metric_contains_required_fields(tmp_path: Path) -> None:
    provider = _SuccessProvider("primary")
    logger = FakeLogger()
    runner = Runner([provider], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-seq")

    events = _run_and_fetch_event(runner, request, metrics_path=tmp_path / "seq.jsonl")
    event = events[0]

    assert event["run_id"] == event["request_fingerprint"]
    assert event["mode"] == RunnerMode.SEQUENTIAL.value
    assert event["providers"] == ["primary"]
    assert event["provider_id"] == event["provider"]
    cost_usd = event["cost_usd"]
    assert isinstance(cost_usd, int | float)
    assert event["cost_estimate"] == pytest.approx(float(cost_usd))

    attempts = event["attempts"]
    assert isinstance(attempts, int)
    retries = event["retries"]
    assert isinstance(retries, int)
    assert retries == attempts - 1
    assert event["outcome"] == "success"
    assert "shadow_provider_id" in event


def test_parallel_run_metric_uses_shadow_default(tmp_path: Path) -> None:
    primary = _SuccessProvider("primary")
    secondary = _SuccessProvider("secondary")
    shadow = _SuccessProvider("shadow")
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ALL, shadow_provider=shadow)
    logger = FakeLogger()
    runner = Runner([primary, secondary], logger=logger, config=config)
    request = ProviderRequest(prompt="hello", model="demo-parallel")

    events = _run_and_fetch_event(runner, request, metrics_path=tmp_path / "parallel.jsonl")

    for event in events:
        assert event["run_id"] == event["request_fingerprint"]
        assert event["mode"] == RunnerMode.PARALLEL_ALL.value
        assert event["providers"] == ["primary", "secondary"]
        assert event["provider_id"] == event["provider"]
        assert event["outcome"] == "success"
        assert event["shadow_used"] is True
        assert event["shadow_provider_id"] == "shadow"
