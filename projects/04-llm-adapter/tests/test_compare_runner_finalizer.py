from __future__ import annotations

from pathlib import Path

from adapter.core.compare_runner_finalizer import DeterminismGate
from adapter.core.datasets import GoldenTask
from adapter.core.metrics.models import RunMetrics
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)

_BASE_METRICS = dict(
    ts="2024-01-01T00:00:00Z",
    run_id="run",
    mode="compare",
    prompt_id="prompt",
    prompt_name="Prompt",
    seed=0,
    temperature=0.0,
    top_p=1.0,
    max_tokens=16,
    input_tokens=1,
    output_tokens=1,
    latency_ms=1,
    cost_usd=0.0,
    status="ok",
    failure_kind=None,
    error_message=None,
    output_hash=None,
)


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        path=Path("provider.yaml"),
        schema_version=1,
        provider="dummy",
        endpoint=None,
        model="dummy-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(
            determinism_diff_rate_max=1e-6,
            determinism_len_stdev_max=1e-6,
        ),
        raw={},
    )


def _metrics(output: str, *, len_tokens: int) -> RunMetrics:
    metrics = RunMetrics(
        provider="dummy",
        model="dummy-model",
        output_text=output,
        **_BASE_METRICS,
    )
    metrics.eval.len_tokens = len_tokens
    metrics.error_message = "existing message"
    return metrics


def test_determinism_gate_appends_diff_stats_to_error_message() -> None:
    gate = DeterminismGate()
    provider_config = _provider_config()
    task = GoldenTask(
        task_id="task",
        name="Task",
        input={},
        prompt_template="",
        expected={},
    )
    metrics_a = _metrics("alpha", len_tokens=2)
    metrics_b = _metrics("beta", len_tokens=8)

    gate.apply(provider_config, task, [metrics_a, metrics_b], ["alpha", "beta"])

    assert metrics_a.error_message is not None
    assert "existing message" in metrics_a.error_message
    assert "median_diff=" in metrics_a.error_message
    assert "len_stdev=" in metrics_a.error_message
