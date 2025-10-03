from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from adapter.core.metrics import BudgetSnapshot
from adapter.core.models import ProviderConfig
from adapter.core.providers import ProviderResponse
from adapter.core.runner_execution import RunnerExecution

if TYPE_CHECKING:
    from adapter.core.datasets import GoldenTask
    from adapter.core.metrics import RunMetrics

    from .conftest import (
        ProviderConfigFactory,
        RunMetricsFactory,
        TaskFactory,
    )


def test_runner_execution_records_shadow_budget_and_schema(
    tmp_path: Path,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    run_metrics_factory: "RunMetricsFactory",
) -> None:
    provider_config = provider_config_factory(
        tmp_path, name="p-main", provider="p-main", model="m1"
    )
    task = task_factory()
    response = ProviderResponse(
        output_text="primary",
        input_tokens=7,
        output_tokens=5,
        latency_ms=27,
        token_usage=SimpleNamespace(prompt=7, completion=5, total=12),
    )
    provider = SimpleNamespace(generate=lambda _prompt: response)
    shadow_latency = 11
    shadow_provider = SimpleNamespace(
        name=lambda: "shadow-mock",
        capabilities=lambda: set(),
        invoke=lambda request: SimpleNamespace(latency_ms=shadow_latency),
    )

    class Validator:
        def validate(self, _text: str) -> None:
            raise ValueError("schema mismatch")

    evaluate_calls: list[tuple[ProviderConfig, float, str, str | None, str | None]] = []

    def evaluate_budget(
        cfg: ProviderConfig,
        cost: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        evaluate_calls.append((cfg, cost, status, failure_kind, error_message))
        return (
            BudgetSnapshot(run_budget_usd=0.0, hit_stop=False),
            "budget-stop",
            status,
            failure_kind,
            error_message,
        )

    def build_metrics(
        cfg: ProviderConfig,
        golden_task: "GoldenTask",
        attempt_index: int,
        mode: str,
        provider_response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
        latency_ms: int,
        budget_snapshot: BudgetSnapshot,
        cost_usd: float,
    ) -> tuple["RunMetrics", str]:
        metrics = run_metrics_factory(
            provider=cfg.provider,
            model=cfg.model,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        metrics.status = status
        metrics.failure_kind = failure_kind
        metrics.error_message = error_message
        metrics.output_text = provider_response.output_text or ""
        return metrics, provider_response.output_text or ""

    execution = RunnerExecution(
        token_bucket=None,
        schema_validator=Validator(),
        evaluate_budget=evaluate_budget,
        build_metrics=build_metrics,
        normalize_concurrency=lambda count, limit: count,
        backoff=None,
        shadow_provider=shadow_provider,
        metrics_path=None,
        provider_weights=None,
    )

    result = execution._run_single(
        provider_config,
        provider,
        task,
        attempt_index=0,
        mode="consensus",
    )

    assert len(evaluate_calls) == 1
    cfg, cost, status, failure_kind, error_message = evaluate_calls[0]
    assert cfg == provider_config
    assert cost == pytest.approx(0.0)
    assert status == "ok"
    assert failure_kind is None
    assert error_message is None
    assert result.stop_reason == "budget-stop"

    metrics = result.metrics
    assert metrics.shadow_provider_id == "shadow-mock"
    assert metrics.shadow_latency_ms == shadow_latency
    assert metrics.shadow_status == "ok"
    assert metrics.shadow_outcome == "success"
    assert metrics.shadow_error_message is None
    assert metrics.status == "error"
    assert metrics.failure_kind == "schema_violation"
    assert metrics.error_message and "schema mismatch" in metrics.error_message
