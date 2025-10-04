from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pytest

# isort: split
from ._sys_path import (
    BudgetManager,
    GoldenTask,
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
    RunMetrics,
)


class ProviderConfigFactory(Protocol):
    def __call__(self, tmp_path: Path, *, name: str, provider: str, model: str) -> ProviderConfig: ...


class TaskFactory(Protocol):
    def __call__(self) -> GoldenTask: ...


class RunMetricsFactory(Protocol):
    def __call__(self, *, provider: str, model: str, latency_ms: int, cost_usd: float) -> RunMetrics: ...


@pytest.fixture
def provider_config_factory() -> ProviderConfigFactory:
    return _make_provider_config


@pytest.fixture
def budget_manager_factory() -> Callable[[], BudgetManager]:
    return _make_budget_manager


@pytest.fixture
def task_factory() -> TaskFactory:
    return _make_task


@pytest.fixture
def run_metrics_factory() -> RunMetricsFactory:
    return _make_run_metrics


def _make_provider_config(
    tmp_path: Path, *, name: str, provider: str, model: str
) -> ProviderConfig:
    return ProviderConfig(
        path=tmp_path / f"{name}.yaml",
        schema_version=1,
        provider=provider,
        endpoint=None,
        model=model,
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
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def _make_budget_manager() -> BudgetManager:
    from adapter.core.models import BudgetBook, BudgetRule

    book = BudgetBook(
        default=BudgetRule(
            run_budget_usd=10.0, daily_budget_usd=10.0, stop_on_budget_exceed=False
        ),
        overrides={},
    )
    return BudgetManager(book)


def _make_task() -> GoldenTask:
    return GoldenTask(
        task_id="t1",
        name="task",
        input={},
        prompt_template="prompt",
        expected={"type": "literal", "value": "YES"},
    )


def _make_run_metrics(
    *, provider: str, model: str, latency_ms: int, cost_usd: float
) -> RunMetrics:
    return RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id="run",
        provider=provider,
        model=model,
        mode="consensus",
        prompt_id="prompt-id",
        prompt_name="prompt",
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        input_tokens=1,
        output_tokens=1,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        status="ok",
        failure_kind=None,
        error_message=None,
        output_text="",
        output_hash=None,
    )


__all__ = [
    "ProviderConfigFactory",
    "TaskFactory",
    "RunMetricsFactory",
    "provider_config_factory",
    "budget_manager_factory",
    "task_factory",
    "run_metrics_factory",
]
