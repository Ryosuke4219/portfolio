import logging
from pathlib import Path

import pytest

from adapter.core.budgets import BudgetBook, BudgetManager, BudgetRule
from adapter.core.compare_runner_support import BudgetEvaluator, RunMetricsBuilder
from adapter.core.config import ProviderConfig
from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot, hash_text
from adapter.core.models import (
    PricingConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import ProviderResponse


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
        expected={"type": "json_equal", "value": {"answer": 1}},
    )


@pytest.fixture(name="provider_response")
def _provider_response() -> ProviderResponse:
    return ProviderResponse(
        output_text="not-json",
        latency_ms=123,
        input_tokens=5,
        output_tokens=7,
    )


@pytest.fixture(name="budget_manager")
def _budget_manager() -> BudgetManager:
    rule = BudgetRule(run_budget_usd=1.0, daily_budget_usd=1.0, stop_on_budget_exceed=True)
    book = BudgetBook(default=rule, overrides={})
    return BudgetManager(book)


def test_run_metrics_builder_merges_eval_failures(
    provider_config: ProviderConfig,
    golden_task: GoldenTask,
    provider_response: ProviderResponse,
) -> None:
    builder = RunMetricsBuilder()
    snapshot = BudgetSnapshot(run_budget_usd=1.0, hit_stop=False)

    run_metrics, output_text = builder.build(
        provider_config=provider_config,
        task=golden_task,
        attempt_index=2,
        mode="parallel-any",
        response=provider_response,
        status="ok",
        failure_kind=None,
        error_message=None,
        latency_ms=provider_response.latency_ms,
        budget_snapshot=snapshot,
        cost_usd=0.5,
    )

    assert run_metrics.status == "error"
    assert run_metrics.failure_kind == "parsing"
    assert run_metrics.output_text == provider_response.output_text
    assert run_metrics.output_hash == hash_text(provider_response.output_text)
    assert run_metrics.eval.len_tokens == provider_response.output_tokens
    assert output_text == provider_response.output_text


def test_run_metrics_builder_sets_cost_estimate(
    provider_config: ProviderConfig,
    golden_task: GoldenTask,
    provider_response: ProviderResponse,
) -> None:
    builder = RunMetricsBuilder()
    snapshot = BudgetSnapshot(run_budget_usd=1.0, hit_stop=False)

    run_metrics, _ = builder.build(
        provider_config=provider_config,
        task=golden_task,
        attempt_index=0,
        mode="parallel-any",
        response=provider_response,
        status="ok",
        failure_kind=None,
        error_message=None,
        latency_ms=provider_response.latency_ms,
        budget_snapshot=snapshot,
        cost_usd=0.5,
    )

    assert run_metrics.cost_estimate == pytest.approx(run_metrics.cost_usd)

    payload = run_metrics.to_json_dict()
    assert payload["cost_estimate"] == pytest.approx(payload["cost_usd"])


def test_budget_evaluator_flags_budget_exceed(
    provider_config: ProviderConfig,
    budget_manager: BudgetManager,
) -> None:
    evaluator = BudgetEvaluator(budget_manager=budget_manager, allow_overrun=False, logger=logging.getLogger(__name__))

    snapshot, stop_reason, status, failure_kind, error_message = evaluator.evaluate(
        provider_config=provider_config,
        cost_usd=2.0,
        status="ok",
        failure_kind=None,
        error_message="preexisting",
    )

    assert snapshot.hit_stop is True
    assert status == "error"
    assert failure_kind == "guard_violation"
    assert "run budget" in error_message
    assert "daily budget" in error_message
    assert error_message.startswith("preexisting | ")
    assert stop_reason == "provider=mock daily budget 1.0000 USD exceeded (spent=2.0000 USD)"
