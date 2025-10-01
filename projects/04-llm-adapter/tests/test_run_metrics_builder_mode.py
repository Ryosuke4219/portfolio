from __future__ import annotations

from enum import Enum
from pathlib import Path

import pytest

from adapter.core.compare_runner_support import RunMetricsBuilder
from adapter.core.config import ProviderConfig
from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot
from adapter.core.models import (
    PricingConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import ProviderResponse


class DummyMode(str, Enum):
    SEQUENTIAL = "sequential"


@pytest.fixture(name="provider_config")
def _provider_config(tmp_path: Path) -> ProviderConfig:
    config_path = tmp_path / "provider.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider="mock",
        endpoint=None,
        model="test-model",
        auth_env=None,
        seed=42,
        temperature=0.1,
        top_p=0.9,
        max_tokens=16,
        timeout_s=30,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


@pytest.fixture(name="golden_task")
def _golden_task() -> GoldenTask:
    return GoldenTask(
        task_id="task-1",
        name="sample",
        input={},
        prompt_template="",
        expected={"type": "literal", "value": "answer"},
    )


@pytest.fixture(name="provider_response")
def _provider_response() -> ProviderResponse:
    return ProviderResponse(
        output_text="answer",
        latency_ms=123,
        input_tokens=5,
        output_tokens=7,
    )


def test_run_metrics_builder_coerces_enum_mode_to_string(
    provider_config: ProviderConfig,
    golden_task: GoldenTask,
    provider_response: ProviderResponse,
) -> None:
    builder = RunMetricsBuilder()
    snapshot = BudgetSnapshot(run_budget_usd=1.0, hit_stop=False)

    run_metrics, _ = builder.build(
        provider_config=provider_config,
        task=golden_task,
        attempt_index=1,
        mode=DummyMode.SEQUENTIAL,
        response=provider_response,
        status="ok",
        failure_kind=None,
        error_message=None,
        latency_ms=provider_response.latency_ms,
        budget_snapshot=snapshot,
        cost_usd=0.5,
    )

    assert isinstance(run_metrics.mode, str)
    assert run_metrics.mode == DummyMode.SEQUENTIAL.value
