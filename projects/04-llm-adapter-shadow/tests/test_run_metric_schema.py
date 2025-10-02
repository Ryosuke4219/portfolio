from __future__ import annotations

from concurrent.futures import CancelledError
from pathlib import Path

import pytest

from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner import Runner, RunnerConfig
from src.llm_adapter.runner_config import RunnerMode
from src.llm_adapter.runner_shared import log_run_metric

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
    tokens_in = event["tokens_in"]
    tokens_out = event["tokens_out"]
    assert event["token_usage"] == {
        "prompt": tokens_in,
        "completion": tokens_out,
        "total": tokens_in + tokens_out,
    }
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
        tokens_in = event["tokens_in"]
        tokens_out = event["tokens_out"]
        assert event["token_usage"] == {
            "prompt": tokens_in,
            "completion": tokens_out,
            "total": tokens_in + tokens_out,
        }
        assert event["outcome"] == "success"
        assert event["shadow_used"] is True
        assert event["shadow_provider_id"] == "shadow"


def test_run_metric_cancellation_reports_success(tmp_path: Path) -> None:
    provider = _SuccessProvider("primary")
    logger = FakeLogger()
    request = ProviderRequest(prompt="hello", model="demo-cancelled")
    metadata = {
        "mode": RunnerMode.SEQUENTIAL.value,
        "providers": [provider.name()],
        "shadow_provider_id": None,
        "trace_id": None,
        "project_id": None,
    }

    log_run_metric(
        logger,
        request_fingerprint="fingerprint",
        request=request,
        provider=provider,
        status="error",
        attempts=1,
        latency_ms=5,
        tokens_in=None,
        tokens_out=None,
        cost_usd=0.0,
        error=CancelledError(),
        metadata=metadata,
        shadow_used=False,
    )

    events = logger.of_type("run_metric")
    assert len(events) == 1
    event = events[0]
    assert event["status"] == "ok"
    assert event["error_type"] is None
    assert event["token_usage"] == {
        "prompt": 0,
        "completion": 0,
        "total": 0,
    }
