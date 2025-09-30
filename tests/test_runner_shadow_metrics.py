"""RunnerExecution のシャドー計測検証。"""
from __future__ import annotations

import contextlib
import logging
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "projects" / "04-llm-adapter"))

from adapter.core.metrics import RunMetrics
from adapter.core.runner_execution import RunnerExecution


BASE_METRICS = RunMetrics(
    ts="2024-01-01T00:00:00Z",
    run_id="run-1",
    provider="main",
    model="model",
    mode="compare",
    prompt_id="task-1",
    prompt_name="task",
    seed=0,
    temperature=0.0,
    top_p=1.0,
    max_tokens=16,
    input_tokens=1,
    output_tokens=1,
    latency_ms=10,
    cost_usd=0.0,
    status="ok",
    failure_kind=None,
    error_message=None,
    output_text="PRIMARY",
    output_hash=None,
)


CONFIG = SimpleNamespace(
    provider="main",
    model="model",
    seed=0,
    temperature=0.0,
    top_p=1.0,
    max_tokens=16,
    timeout_s=30,
    persist_output=True,
    pricing=SimpleNamespace(
        prompt_usd=0.0,
        completion_usd=0.0,
        input_per_million=0.0,
        output_per_million=0.0,
    ),
)
RESPONSE = SimpleNamespace(
    output_text="PRIMARY",
    input_tokens=3,
    output_tokens=2,
    latency_ms=12,
    token_usage=SimpleNamespace(prompt=3, completion=2, total=5),
)
TASK = type("Task", (), {"task_id": "task-1", "name": "task", "render_prompt": lambda self: "say hi"})()


def _run_shadow(shadow, *, expect_error: bool, caplog: pytest.LogCaptureFixture):
    config = CONFIG
    response = RESPONSE
    task = TASK

    def build_metrics(cfg, task_obj, _attempt, mode, resp, status, failure, error, latency, _budget, cost):
        metrics = replace(BASE_METRICS)
        metrics.mode = mode
        metrics.input_tokens = resp.input_tokens
        metrics.output_tokens = resp.output_tokens
        metrics.latency_ms = latency
        metrics.cost_usd = cost
        metrics.status = status
        metrics.failure_kind = failure
        metrics.error_message = error
        metrics.output_text = resp.output_text
        return metrics, resp.output_text

    execution = RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=lambda cfg, cost, status, failure, error: (
            SimpleNamespace(run_budget_usd=0.0, hit_stop=False),
            None,
            status,
            failure,
            error,
        ),
        build_metrics=build_metrics,
        normalize_concurrency=lambda total, limit: total,
        backoff=None,
        shadow_provider=shadow,
        metrics_path=None,
        provider_weights=None,
    )
    provider = SimpleNamespace(generate=lambda _prompt: response)
    context = caplog.at_level(logging.ERROR) if expect_error else contextlib.nullcontext()
    with context:
        return execution._run_single(config, provider, task, 0, "compare")


@pytest.mark.parametrize(
    "shadow_factory, expected_status, expected_outcome, expected_error, expect_log",
    [
        (
            lambda: SimpleNamespace(
                name=lambda: "shadow-probe",
                capabilities=lambda: set(),
                invoke=lambda request: SimpleNamespace(latency_ms=7),
            ),
            "ok",
            "success",
            None,
            False,
        ),
        (
            lambda: SimpleNamespace(
                name=lambda: "shadow-probe",
                capabilities=lambda: set(),
                invoke=lambda _request: (_ for _ in ()).throw(RuntimeError("shadow boom")),
            ),
            "error",
            "error",
            "shadow boom",
            True,
        ),
    ],
)
def test_shadow_metrics_capture(shadow_factory, expected_status, expected_outcome, expected_error, expect_log, caplog):
    result = _run_shadow(shadow_factory(), expect_error=expect_log, caplog=caplog)
    metrics = result.metrics
    assert metrics.shadow_provider_id == "shadow-probe"
    assert metrics.shadow_status == expected_status
    assert metrics.shadow_outcome == expected_outcome
    assert metrics.shadow_error_message == expected_error
    if expected_status == "ok":
        assert metrics.shadow_latency_ms == 7
    if expect_log:
        assert "Shadow provider shadow-probe failed" in caplog.text
