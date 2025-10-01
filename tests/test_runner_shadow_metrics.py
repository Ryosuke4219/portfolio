"""RunnerExecution のシャドー計測検証。"""
from __future__ import annotations

from collections.abc import Callable
import contextlib
from dataclasses import replace
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "projects" / "04-llm-adapter"))

from adapter.core.errors import RateLimitError
from adapter.core.metrics import RunMetrics
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
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

BASE_CONFIG = ProviderConfig(
    path=Path("provider.yaml"),
    schema_version=1,
    provider="main",
    endpoint=None,
    model="model",
    auth_env=None,
    seed=0,
    temperature=0.0,
    top_p=1.0,
    max_tokens=16,
    timeout_s=30,
    retries=RetryConfig(),
    persist_output=True,
    pricing=PricingConfig(),
    rate_limit=RateLimitConfig(),
    quality_gates=QualityGatesConfig(),
    raw={},
)

RESPONSE = SimpleNamespace(
    output_text="PRIMARY",
    input_tokens=3,
    output_tokens=2,
    latency_ms=12,
    token_usage=SimpleNamespace(prompt=3, completion=2, total=5),
)

TASK = type(
    "Task",
    (),
    {"task_id": "task-1", "name": "task", "render_prompt": lambda self: "say hi"},
)()


def _build_metrics() -> Callable:
    def build_metrics(
        cfg,
        task_obj,
        _attempt,
        mode,
        resp,
        status,
        failure,
        error,
        latency,
        _budget,
        cost,
    ):
        metrics = replace(BASE_METRICS)
        metrics.provider = cfg.provider
        metrics.model = cfg.model
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

    return build_metrics


def _make_execution(shadow) -> RunnerExecution:
    return RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=lambda cfg, cost, status, failure, error: (
            SimpleNamespace(run_budget_usd=0.0, hit_stop=False),
            None,
            status,
            failure,
            error,
        ),
        build_metrics=_build_metrics(),
        normalize_concurrency=lambda total, limit: total,
        backoff=None,
        shadow_provider=shadow,
        metrics_path=None,
        provider_weights=None,
    )


def _run_single(
    *,
    provider,
    shadow,
    config: ProviderConfig | None,
    expect_error: bool,
    caplog: pytest.LogCaptureFixture,
):
    execution = _make_execution(shadow)
    context = caplog.at_level(logging.ERROR) if expect_error else contextlib.nullcontext()
    with context:
        return execution._run_single(config or BASE_CONFIG, provider, TASK, 0, "compare")


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
def test_shadow_metrics_capture(
    shadow_factory,
    expected_status,
    expected_outcome,
    expected_error,
    expect_log,
    caplog,
):
    provider = SimpleNamespace(generate=lambda _prompt: RESPONSE)
    result = _run_single(
        provider=provider,
        shadow=shadow_factory(),
        config=None,
        expect_error=expect_log,
        caplog=caplog,
    )
    metrics = result.metrics
    assert metrics.shadow_provider_id == "shadow-probe"
    assert metrics.shadow_status == expected_status
    assert metrics.shadow_outcome == expected_outcome
    assert metrics.shadow_error_message == expected_error
    if expected_status == "ok":
        assert metrics.shadow_latency_ms == 7
    if expect_log:
        assert "Shadow provider shadow-probe failed" in caplog.text


def test_run_single_retries_rate_limit_preserves_shadow_metrics(caplog: pytest.LogCaptureFixture):
    config = replace(BASE_CONFIG, retries=RetryConfig(max=1, backoff_s=0.0))
    shadow_calls: list[object] = []

    class ShadowProvider:
        def name(self) -> str:
            return "shadow-probe"

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request):
            shadow_calls.append(request)
            return SimpleNamespace(latency_ms=11)

    call_count = 0

    def generate(prompt: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RateLimitError("rate limited")
        return RESPONSE

    provider = SimpleNamespace(generate=generate)
    result = _run_single(
        provider=provider,
        shadow=ShadowProvider(),
        config=config,
        expect_error=False,
        caplog=caplog,
    )

    metrics = result.metrics
    assert call_count == 2
    assert len(shadow_calls) == 1
    assert metrics.status == "ok"
    assert metrics.retries == 1
    assert metrics.shadow_provider_id == "shadow-probe"
    assert metrics.shadow_status == "ok"
    assert metrics.shadow_outcome == "success"
    assert metrics.shadow_latency_ms == 11
