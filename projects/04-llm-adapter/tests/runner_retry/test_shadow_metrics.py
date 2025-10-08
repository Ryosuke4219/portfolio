from __future__ import annotations

from types import SimpleNamespace

from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot, RunMetrics
from adapter.core.models import ProviderConfig
from adapter.core.provider_spi import TokenUsage
from adapter.core.providers import ProviderResponse
from adapter.core.runner_execution import RunnerExecution

from .conftest import make_provider_config, make_task, TrackingProvider, UnusedProvider


class _ShadowProvider:
    def __init__(self, latency_ms: int) -> None:
        self._latency_ms = latency_ms

    def name(self) -> str:
        return "shadow-test"

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: object) -> SimpleNamespace:
        return SimpleNamespace(latency_ms=self._latency_ms)


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
        run_id="run-primary",
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


def test_run_sequential_attempt_updates_metrics_and_shadow(tmp_path) -> None:
    primary_config = make_provider_config(tmp_path, "primary")
    backup_config = make_provider_config(tmp_path, "backup")
    task = make_task()
    provider_response = ProviderResponse(
        output_text="primary-response",
        input_tokens=3,
        output_tokens=2,
        latency_ms=17,
        token_usage=TokenUsage(prompt=3, completion=2),
    )
    primary_provider = TrackingProvider(primary_config, provider_response)
    backup_provider = UnusedProvider(backup_config)
    shadow_latency = 9

    execution = RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=_evaluate_budget,
        build_metrics=_build_metrics,
        normalize_concurrency=lambda count, limit: count,
        backoff=None,
        shadow_provider=_ShadowProvider(shadow_latency),
        metrics_path=None,
        provider_weights=None,
    )

    batch, stop_reason = execution.run_sequential_attempt(
        [
            (primary_config, primary_provider),
            (backup_config, backup_provider),
        ],
        task,
        attempt_index=1,
        mode="sequential",
    )

    assert stop_reason is None
    assert len(batch) == 1
    assert primary_provider.calls == 1

    metrics = batch[0][1].metrics
    assert metrics.providers == ["primary", "backup"]
    assert metrics.token_usage == {"prompt": 3, "completion": 2, "total": 5}
    assert metrics.attempts == 2
    assert metrics.retries == 1
    assert metrics.outcome == "success"
    assert metrics.shadow_provider_id == "shadow-test"
    assert metrics.shadow_latency_ms == shadow_latency
    assert metrics.shadow_status == "ok"
    assert metrics.shadow_outcome == "success"
    assert metrics.shadow_error_message is None


__all__ = ["test_run_sequential_attempt_updates_metrics_and_shadow"]
