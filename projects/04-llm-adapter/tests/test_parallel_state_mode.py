from __future__ import annotations

from enum import Enum
from pathlib import Path

from adapter.core.datasets import GoldenTask
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.parallel_state import build_cancelled_result
from adapter.core.runner_api import RunnerConfig


class RunnerMode(str, Enum):
    PARALLEL_ANY = "parallel_any"


def _make_provider_config(tmp_path: Path) -> ProviderConfig:
    return ProviderConfig(
        path=tmp_path / "provider.yaml",
        schema_version=1,
        provider="provider",
        endpoint=None,
        model="model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=1,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def _make_task() -> GoldenTask:
    return GoldenTask(
        task_id="task",
        name="Task",
        input={},
        prompt_template="template",
        expected={},
    )


def test_build_cancelled_result_uses_mode_value(tmp_path: Path) -> None:
    provider_config = _make_provider_config(tmp_path)
    task = _make_task()
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ANY)  # type: ignore[arg-type]

    result = build_cancelled_result(
        provider_config,
        task,
        attempt_index=0,
        config=config,
        cancel_message="cancel",
    )

    metrics = result.metrics
    assert metrics.mode == RunnerMode.PARALLEL_ANY.value
    assert type(metrics.mode) is str
