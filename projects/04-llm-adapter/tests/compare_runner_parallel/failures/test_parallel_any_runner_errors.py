from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from adapter.core import _parallel_shim, errors
from adapter.core.config import ProviderConfig
from adapter.core.errors import AuthError, ConfigError, ProviderSkip, TimeoutError
from adapter.core.metrics.models import BudgetSnapshot, RunMetrics
from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import RunnerExecution
from adapter.core.runner_execution_parallel import ProviderFailureSummary
from tests.compare_runner_parallel.conftest import (
    ProviderConfigFactory,
    RunMetricsFactory,
    TaskFactory,
)

from .common import create_runner, ProviderSetup


@pytest.fixture
def failure_summaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> dict[str, ProviderFailureSummary]:
    class SkipProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            raise ProviderSkip("skip me")

    class TimeoutProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            raise TimeoutError("deadline")

    runner = create_runner(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        budget_manager_factory=budget_manager_factory,
        providers=[
            ProviderSetup(
                registry_name="skip",
                config_name="skip",
                model_name="skip-model",
                provider_cls=SkipProvider,
            ),
            ProviderSetup(
                registry_name="timeout",
                config_name="timeout",
                model_name="timeout-model",
                provider_cls=TimeoutProvider,
            ),
        ],
        metrics_filename="metrics_failure_summary.jsonl",
    )

    with pytest.raises((errors.ParallelExecutionError, _parallel_shim.ParallelExecutionError)) as exc_info:
        runner.run(repeat=1, config=RunnerConfig(mode="parallel_any", max_concurrency=2))

    failures = getattr(exc_info.value, "failures", ())
    assert len(failures) == 2
    return {failure.provider: failure for failure in failures}


@pytest.mark.parametrize(
    ("provider_name", "expectation"),
    [
        (
            "skip",
            {
                "status": "skip",
                "failure_kind": "skip",
                "error_message": "skip me",
                "backoff_next_provider": True,
                "retries": 0,
                "error_type": "ProviderSkip",
            },
        ),
        (
            "timeout",
            {
                "status": "error",
                "failure_kind": "timeout",
                "error_message": "deadline",
                "backoff_next_provider": False,
                "retries": 0,
                "error_type": "TimeoutError",
            },
        ),
    ],
)
def test_parallel_any_failure_summary_includes_all_failures(
    failure_summaries: dict[str, ProviderFailureSummary],
    provider_name: str,
    expectation: dict[str, object],
) -> None:
    summary = failure_summaries[provider_name]
    for field, value in expectation.items():
        assert getattr(summary, field) == value


@pytest.mark.parametrize(
    ("exception_factory", "expected_status", "expected_kind", "message"),
    [
        (lambda: ProviderSkip("skip me"), "skip", "skip", "skip me"),
        (lambda: AuthError("auth fail"), "error", "auth", "auth fail"),
        (lambda: ConfigError("config fail"), "error", "config", "config fail"),
    ],
)
def test_parallel_any_non_billable_errors_have_zero_cost(
    exception_factory: Callable[[], Exception],
    expected_status: str,
    expected_kind: str,
    message: str,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    run_metrics_factory: RunMetricsFactory,
) -> None:
    class ErrorProvider(BaseProvider):
        def __init__(
            self, config: ProviderConfig, factory: Callable[[], Exception]
        ) -> None:
            super().__init__(config)
            self._factory = factory

        def generate(self, prompt: str) -> ProviderResponse:
            raise self._factory()

    provider_config = provider_config_factory(
        tmp_path, name="error", provider="error-provider", model="error-model"
    )
    provider = ErrorProvider(provider_config, exception_factory)
    task = task_factory()

    budget_calls: list[float] = []

    def evaluate_budget(
        cfg: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        budget_calls.append(cost_usd)
        assert cost_usd == pytest.approx(0.0)
        assert status == expected_status
        assert failure_kind == expected_kind
        assert error_message == message
        return (
            BudgetSnapshot(run_budget_usd=0.0, hit_stop=False),
            None,
            status,
            failure_kind,
            error_message,
        )

    def build_metrics(
        cfg: ProviderConfig,
        golden_task,
        attempt_index: int,
        mode: str,
        provider_response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
        latency_ms: int,
        budget_snapshot: BudgetSnapshot,
        cost_usd: float,
    ) -> tuple[RunMetrics, str]:
        assert cost_usd == pytest.approx(0.0)
        assert provider_response.input_tokens == 0
        assert provider_response.output_tokens == 0
        metrics = run_metrics_factory(
            provider=cfg.provider,
            model=cfg.model,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        metrics.status = status
        metrics.failure_kind = failure_kind
        metrics.error_message = error_message
        metrics.input_tokens = provider_response.input_tokens
        metrics.output_tokens = provider_response.output_tokens
        return metrics, provider_response.output_text or ""

    execution = RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=evaluate_budget,
        build_metrics=build_metrics,
        normalize_concurrency=lambda count, limit: count,
        backoff=None,
        shadow_provider=None,
        metrics_path=None,
        provider_weights=None,
    )

    result = execution._run_single(
        provider_config,
        provider,
        task,
        attempt_index=0,
        mode="parallel_any",
    )

    assert len(budget_calls) == 1
    assert budget_calls[0] == pytest.approx(0.0)
    assert result.stop_reason is None
    metrics = result.metrics
    assert metrics.cost_usd == pytest.approx(0.0)
    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.token_usage == {"prompt": 0, "completion": 0, "total": 0}
    assert metrics.status == expected_status
    assert metrics.failure_kind == expected_kind
    assert metrics.error_message == message
