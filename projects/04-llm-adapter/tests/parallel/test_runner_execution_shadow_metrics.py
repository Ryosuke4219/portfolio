from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot, RunMetrics
from adapter.core.models import ProviderConfig
from adapter.core.provider_spi import TokenUsage
from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.runner_config_builder import RunnerConfig, RunnerMode
from adapter.core.runner_execution import RunnerExecution


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
        run_id="run-parallel",
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


class _StaticProvider(BaseProvider):
    def __init__(self, config: ProviderConfig, response: ProviderResponse) -> None:
        super().__init__(config)
        self._response = response

    def invoke(self, request: object) -> ProviderResponse:
        return self._response


def test_run_parallel_attempt_updates_metrics_and_shadow(
    make_provider_config: Callable[[str], ProviderConfig],
    golden_task: GoldenTask,
) -> None:
    primary_config = make_provider_config("primary")
    backup_config = make_provider_config("backup")
    primary_response = ProviderResponse(
        output_text="primary-parallel",
        input_tokens=5,
        output_tokens=4,
        latency_ms=18,
        token_usage=TokenUsage(prompt=5, completion=4),
    )
    backup_response = ProviderResponse(
        output_text="backup-parallel",
        input_tokens=4,
        output_tokens=3,
        latency_ms=16,
        token_usage=TokenUsage(prompt=4, completion=3),
    )
    primary_provider = _StaticProvider(primary_config, primary_response)
    backup_provider = _StaticProvider(backup_config, backup_response)
    shadow_latency = 13

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
    config = RunnerConfig(mode=RunnerMode.PARALLEL_ALL)

    batch, stop_reason = execution.run_parallel_attempt(
        [
            (primary_config, primary_provider),
            (backup_config, backup_provider),
        ],
        golden_task,
        attempt_index=0,
        config=config,
    )

    assert stop_reason is None
    assert len(batch) == 2

    primary_metrics = batch[0][1].metrics
    assert primary_metrics.providers == ["primary", "backup"]
    assert primary_metrics.token_usage == {"prompt": 5, "completion": 4, "total": 9}
    assert primary_metrics.attempts == 1
    assert primary_metrics.retries == 0
    assert primary_metrics.outcome == "success"
    assert primary_metrics.shadow_provider_id == "shadow-test"
    assert primary_metrics.shadow_latency_ms == shadow_latency
    assert primary_metrics.shadow_status == "ok"
    assert primary_metrics.shadow_outcome == "success"
    assert primary_metrics.shadow_error_message is None
    assert batch[0][1].raw_output == "primary-parallel"


__all__ = ["test_run_parallel_attempt_updates_metrics_and_shadow"]
