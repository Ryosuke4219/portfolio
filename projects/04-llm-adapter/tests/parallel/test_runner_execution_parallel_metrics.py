from __future__ import annotations

from types import SimpleNamespace

import pytest

from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot, RunMetrics
from adapter.core.models import ProviderConfig
from adapter.core.provider_spi import ProviderRequest, TokenUsage
from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.runner_api import RunnerConfig, RunnerMode
from adapter.core.runner_execution import RunnerExecution

from ..runner_retry.conftest import make_provider_config, make_task


class _ShadowProvider:
    def __init__(self, latency_ms: int) -> None:
        self._latency_ms = latency_ms

    def name(self) -> str:
        return "shadow-test"

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: object) -> SimpleNamespace:
        return SimpleNamespace(latency_ms=self._latency_ms)


class _StaticProvider(BaseProvider):
    def __init__(self, config: ProviderConfig, response: ProviderResponse) -> None:
        super().__init__(config)
        self._response = response
        self.calls = 0

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return self._response


@pytest.fixture()
def runner_execution_parallel() -> RunnerExecution:
    def _evaluate_budget(
        provider_config: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        return BudgetSnapshot(0.0, False), None, status, failure_kind, error_message

    def _build_metrics(
        provider_config: ProviderConfig,
        task_obj: GoldenTask,
        attempt_index: int,
        mode: str,
        response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
        latency_ms: int,
        budget_snapshot: BudgetSnapshot,
        cost_usd: float,
    ) -> tuple[RunMetrics, str]:
        metrics = RunMetrics(
            ts="2024-01-01T00:00:00Z",
            run_id=f"run-{provider_config.provider}",
            provider=provider_config.provider,
            model=provider_config.model,
            mode=mode,
            prompt_id=task_obj.task_id,
            prompt_name=task_obj.name,
            seed=provider_config.seed,
            temperature=provider_config.temperature,
            top_p=provider_config.top_p,
            max_tokens=provider_config.max_tokens,
            input_tokens=int(response.input_tokens),
            output_tokens=int(response.output_tokens),
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            failure_kind=failure_kind,
            error_message=error_message,
            output_text=response.output_text,
            output_hash=None,
            budget=budget_snapshot,
        )
        return metrics, response.output_text or ""

    return RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=_evaluate_budget,
        build_metrics=_build_metrics,
        normalize_concurrency=lambda total, limit: total,
        backoff=None,
        shadow_provider=_ShadowProvider(latency_ms=9),
        metrics_path=None,
        provider_weights=None,
    )


def test_run_parallel_attempt_propagates_metrics_and_shadow(
    runner_execution_parallel: RunnerExecution, tmp_path
) -> None:
    task = make_task()
    primary_config = make_provider_config(tmp_path, "primary")
    secondary_config = make_provider_config(tmp_path, "secondary")
    primary_response = ProviderResponse(
        output_text="primary",
        input_tokens=4,
        output_tokens=2,
        latency_ms=15,
        token_usage=TokenUsage(prompt=4, completion=2),
    )
    secondary_response = ProviderResponse(
        output_text="secondary",
        input_tokens=3,
        output_tokens=1,
        latency_ms=20,
        token_usage=TokenUsage(prompt=3, completion=1),
    )
    primary_provider = _StaticProvider(primary_config, primary_response)
    secondary_provider = _StaticProvider(secondary_config, secondary_response)

    config = RunnerConfig(mode=RunnerMode.PARALLEL_ALL)

    batch, stop_reason = runner_execution_parallel.run_parallel_attempt(
        [
            (primary_config, primary_provider),
            (secondary_config, secondary_provider),
        ],
        task,
        attempt_index=1,
        config=config,
    )

    assert stop_reason is None
    assert len(batch) == 2

    results = {index: result for index, result in batch}
    primary_metrics = results[0].metrics
    secondary_metrics = results[1].metrics

    for metrics, expected in (
        (primary_metrics, "primary"),
        (secondary_metrics, "secondary"),
    ):
        assert metrics.status == "ok"
        assert metrics.providers == ["primary", "secondary"]
        assert metrics.token_usage["total"] == metrics.token_usage["prompt"] + metrics.token_usage["completion"]
        assert metrics.attempts == 2
        assert metrics.retries == 1
        assert metrics.shadow_provider_id == "shadow-test"
        assert metrics.shadow_latency_ms == 9
        assert metrics.shadow_status == "ok"
        assert metrics.shadow_outcome == "success"
        assert metrics.shadow_error_message is None
        assert metrics.provider == expected


__all__ = [
    "test_run_parallel_attempt_propagates_metrics_and_shadow",
]
