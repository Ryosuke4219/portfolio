from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core.budgets import BudgetManager
from adapter.core.models import (
    BudgetBook,
    BudgetRule,
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot
from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.runners import CompareRunner


@pytest.fixture
def provider_config(tmp_path: Path) -> ProviderConfig:
    return ProviderConfig(
        path=tmp_path / "config.yaml",
        schema_version=1,
        provider="stub",
        endpoint=None,
        model="test-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=0,
        retries=RetryConfig(),
        persist_output=True,
        pricing=PricingConfig(prompt_usd=0.0, completion_usd=0.0),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


@pytest.fixture
def runner(tmp_path: Path, provider_config: ProviderConfig) -> CompareRunner:
    book = BudgetBook(
        default=BudgetRule(run_budget_usd=1.0, daily_budget_usd=1.0, stop_on_budget_exceed=True),
        overrides={},
    )
    manager = BudgetManager(book)
    return CompareRunner([provider_config], [], manager, tmp_path / "metrics.jsonl")


def test_run_provider_call_handles_exception(
    runner: CompareRunner, provider_config: ProviderConfig
) -> None:
    class ExplodingProvider(BaseProvider):
        def __init__(self) -> None:
            super().__init__(provider_config)

        def generate(self, prompt: str) -> ProviderResponse:
            raise RuntimeError("boom")

    response, status, failure_kind, error_message, latency_ms = runner._run_provider_call(
        provider_config, ExplodingProvider(), "hello world"
    )
    assert status == "error"
    assert failure_kind == "provider_error"
    assert error_message and "boom" in error_message
    assert response.output_text == ""
    assert response.output_tokens == 0
    assert response.input_tokens == len("hello world".split())
    assert latency_ms == response.latency_ms


def test_run_provider_call_flags_guard_violation(
    runner: CompareRunner, provider_config: ProviderConfig
) -> None:
    class EmptyProvider(BaseProvider):
        def __init__(self) -> None:
            super().__init__(provider_config)

        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(
                output_text="   ",
                input_tokens=1,
                output_tokens=0,
                latency_ms=10,
            )

    response, status, failure_kind, _, _ = runner._run_provider_call(
        provider_config, EmptyProvider(), "hello"
    )
    assert status == "error"
    assert failure_kind == "guard_violation"
    assert response.output_text.strip() == ""


def test_evaluate_budget_enforces_limits(
    runner: CompareRunner, provider_config: ProviderConfig
) -> None:
    budget_snapshot, stop_reason, status, failure_kind, error_message = runner._evaluate_budget(
        provider_config,
        cost_usd=2.0,
        status="ok",
        failure_kind=None,
        error_message=None,
    )
    assert budget_snapshot.run_budget_usd == 1.0
    assert budget_snapshot.hit_stop is True
    assert stop_reason and "daily budget" in stop_reason
    assert status == "error"
    assert failure_kind == "guard_violation"
    assert error_message and provider_config.provider in error_message


def test_build_metrics_respects_existing_failure(
    runner: CompareRunner, provider_config: ProviderConfig
) -> None:
    task = GoldenTask(
        task_id="t1",
        name="test",
        input={},
        prompt_template="hello",
        expected={"type": "literal", "value": "ok"},
    )
    response = ProviderResponse(
        output_text="ng",
        input_tokens=2,
        output_tokens=1,
        latency_ms=50,
    )
    budget = BudgetSnapshot(run_budget_usd=1.0, hit_stop=True)
    metrics, raw_output = runner._build_metrics(
        provider_config,
        task,
        attempt_index=0,
        mode="eval",
        response=response,
        status="error",
        failure_kind="guard_violation",
        error_message="budget hit",
        latency_ms=50,
        budget_snapshot=budget,
        cost_usd=0.1,
    )
    assert metrics.status == "error"
    assert metrics.failure_kind == "guard_violation"
    assert metrics.error_message == "budget hit"
    assert metrics.budget == budget
    assert metrics.output_hash is not None
    assert raw_output == "ng"
