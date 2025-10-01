from __future__ import annotations

from dataclasses import dataclass

import pytest

from adapter.core.compare_runner_support import RunMetricsBuilder
from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot
from adapter.core.provider_spi import TokenUsage
from adapter.core.providers import ProviderResponse
from adapter.core.runner_api import RunnerMode


@dataclass
class _StubProviderConfig:
    provider: str = "provider"
    model: str = "model"
    persist_output: bool = False
    seed: int = 0
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 256


@pytest.mark.parametrize(
    "mode_input",
    [RunnerMode.PARALLEL_ANY, "parallel-any"],
)
def test_run_metrics_mode_is_canonical(mode_input: RunnerMode | str) -> None:
    builder = RunMetricsBuilder()
    provider_config = _StubProviderConfig()
    task = GoldenTask(
        task_id="task",
        name="Task",
        input={},
        prompt_template="",
        expected={},
    )
    response = ProviderResponse(
        text="output",
        latency_ms=42,
        token_usage=TokenUsage(prompt=1, completion=1),
    )

    run_metrics, _ = builder.build(
        provider_config=provider_config,  # type: ignore[arg-type]
        task=task,
        attempt_index=0,
        mode=mode_input,
        response=response,
        status="ok",
        failure_kind=None,
        error_message=None,
        latency_ms=response.latency_ms,
        budget_snapshot=BudgetSnapshot(run_budget_usd=1.0, hit_stop=False),
        cost_usd=0.01,
    )

    assert run_metrics.mode == "parallel_any"
