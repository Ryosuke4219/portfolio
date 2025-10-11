from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core.datasets import GoldenTask
from adapter.core.metrics import BudgetSnapshot, RunMetrics
from adapter.core.models import ProviderConfig, RetryConfig
from adapter.core.providers import ProviderResponse
from adapter.core.runner_api import BackoffPolicy
from adapter.core.runner_execution import RunnerExecution

from .conftest import (
    make_provider_config,
    make_task,
    RateLimitStubProvider,
    SuccessProvider,
)


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


class CountingTokenBucket:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


def test_rate_limit_retry_invokes_token_bucket_per_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("adapter.core.runner_execution.sleep", lambda _seconds: None)
    task = make_task()
    retry_config = RetryConfig(max=1, backoff_s=0.1)
    provider_config = make_provider_config(tmp_path, "rate-limit", retries=retry_config)
    provider = RateLimitStubProvider(provider_config, failures=1)
    token_bucket = CountingTokenBucket()

    execution = RunnerExecution(
        token_bucket=token_bucket,
        schema_validator=None,
        evaluate_budget=_evaluate_budget,
        build_metrics=_build_metrics,
        normalize_concurrency=lambda total, limit: total,
        backoff=BackoffPolicy(timeout_next_provider=False, retryable_next_provider=False),
        shadow_provider=None,
        metrics_path=None,
        provider_weights=None,
    )

    execution.run_sequential_attempt(
        [(provider_config, provider)],
        task,
        attempt_index=0,
        mode="sequential",
    )

    assert token_bucket.calls == 2


def test_rate_limit_retry_advances_after_max(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("adapter.core.runner_execution.sleep", lambda _seconds: None)
    task = make_task()
    retry_config = RetryConfig(max=1, backoff_s=0.1)
    failing_config = make_provider_config(tmp_path, "rate-limit", retries=retry_config)
    success_config = make_provider_config(tmp_path, "next")
    failing_provider = RateLimitStubProvider(failing_config, failures=2)
    success_provider = SuccessProvider(success_config)

    execution = RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=_evaluate_budget,
        build_metrics=_build_metrics,
        normalize_concurrency=lambda total, limit: total,
        backoff=BackoffPolicy(timeout_next_provider=False, retryable_next_provider=False),
        shadow_provider=None,
        metrics_path=None,
        provider_weights=None,
    )

    batch, stop_reason = execution.run_sequential_attempt(
        [
            (failing_config, failing_provider),
            (success_config, success_provider),
        ],
        task,
        attempt_index=0,
        mode="sequential",
    )

    assert stop_reason is None
    assert failing_provider.calls == 2
    assert len(batch) == 2
    first_result = batch[0][1]
    assert first_result.metrics.status == "error"
    assert first_result.metrics.retries == 1
    assert first_result.backoff_next_provider is True
    second_result = batch[1][1]
    assert second_result.metrics.status == "ok"
    assert second_result.metrics.retries == 0


__all__ = [
    "test_rate_limit_retry_invokes_token_bucket_per_attempt",
    "test_rate_limit_retry_advances_after_max",
]
