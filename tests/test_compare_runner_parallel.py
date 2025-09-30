import json
from pathlib import Path
from typing import Any

import pytest

from adapter.core.budgets import BudgetManager
from adapter.core.datasets import GoldenTask
from adapter.core.errors import AllFailedError
from adapter.core.metrics import BudgetSnapshot, RunMetrics
from adapter.core.models import (
    BudgetBook,
    BudgetRule,
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.providers import BaseProvider, ProviderFactory, ProviderResponse
from adapter.core.runner_api import BackoffPolicy, RunnerConfig
from adapter.core.runner_execution import RunnerExecution
from adapter.core.runners import CompareRunner


class ScriptedProvider(BaseProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        raw_script = config.raw.get("script") if isinstance(config.raw, dict) else None
        if not isinstance(raw_script, list):  # pragma: no cover - guard
            raw_script = []
        self._script: list[dict[str, Any]] = [dict(entry) for entry in raw_script]
        self.call_count = 0

    def generate(self, prompt: str) -> ProviderResponse:
        if self.call_count >= len(self._script):
            raise RuntimeError("script exhausted")
        entry = self._script[self.call_count]
        self.call_count += 1
        exc_name = entry.get("exception")
        message = entry.get("message", exc_name or "")
        if exc_name:
            if exc_name == "auth":
                from adapter.core.errors import AuthError

                raise AuthError(message or "auth error")
            if exc_name == "rate_limit":
                from adapter.core.errors import RateLimitError

                raise RateLimitError(message or "rate limit")
            if exc_name == "retryable":
                from adapter.core.errors import RetriableError

                raise RetriableError(message or "retryable")
            if exc_name == "timeout":
                from adapter.core.errors import TimeoutError

                raise TimeoutError(message or "timeout")
            if exc_name == "skip":
                from adapter.core.errors import ProviderSkip

                raise ProviderSkip(message or "skip")
            raise RuntimeError(message or exc_name)
        return ProviderResponse(
            output_text=entry.get("output", ""),
            input_tokens=int(entry.get("input_tokens", 1)),
            output_tokens=int(entry.get("output_tokens", 1)),
            latency_ms=int(entry.get("latency_ms", 1)),
        )


def _make_provider_config(name: str, *, retries: int = 0, script: list[dict[str, Any]] | None = None) -> ProviderConfig:
    return ProviderConfig(
        path=Path(f"{name}.yaml"),
        schema_version=1,
        provider=name,
        endpoint=None,
        model="test-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=128,
        timeout_s=30,
        retries=RetryConfig(max=retries, backoff_s=0.0),
        persist_output=True,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={"script": script or []},
    )


def _make_task() -> GoldenTask:
    return GoldenTask(
        task_id="task-1",
        name="demo",
        input={},
        prompt_template="hello",
        expected={},
    )


def _build_metrics(
    provider_config: ProviderConfig,
    task: GoldenTask,
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
        ts="now",
        run_id=f"run-{task.task_id}-{attempt_index}",
        provider=provider_config.provider,
        model=provider_config.model,
        mode=mode,
        prompt_id=task.task_id,
        prompt_name=task.name,
        seed=provider_config.seed,
        temperature=provider_config.temperature,
        top_p=provider_config.top_p,
        max_tokens=provider_config.max_tokens,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        status=status,
        failure_kind=failure_kind,
        error_message=error_message,
        output_text=response.output_text,
        output_hash=None,
    )
    return metrics, response.output_text


def _make_execution(
    providers: list[tuple[ProviderConfig, BaseProvider]],
    *,
    backoff: BackoffPolicy | None = None,
) -> RunnerExecution:
    def evaluate_budget(
        provider_config: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        return BudgetSnapshot(0.0, False), None, status, failure_kind, error_message

    def normalize(total: int, limit: int | None) -> int:
        if limit is None or limit <= 0:
            return total
        return max(1, min(total, limit))

    return RunnerExecution(
        token_bucket=None,
        schema_validator=None,
        evaluate_budget=evaluate_budget,
        build_metrics=_build_metrics,
        normalize_concurrency=normalize,
        backoff=backoff,
        shadow_provider=None,
        metrics_path=None,
        provider_weights=None,
    )


def test_sequential_stops_at_first_success() -> None:
    provider_a_config = _make_provider_config(
        "primary",
        script=[{"output": "ok"}],
    )
    provider_b_config = _make_provider_config(
        "secondary",
        script=[{"output": "unused"}],
    )
    provider_a = ScriptedProvider(provider_a_config)
    provider_b = ScriptedProvider(provider_b_config)
    providers = [(provider_a_config, provider_a), (provider_b_config, provider_b)]
    execution = _make_execution(providers)
    task = _make_task()

    batch, stop_reason = execution.run_sequential_attempt(providers, task, 0, "sequential")

    assert stop_reason is None
    assert len(batch) == 1
    assert provider_a.call_count == 1
    assert provider_b.call_count == 0
    assert batch[0][1].metrics.status == "ok"


def test_rate_limit_retries_before_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_a_config = _make_provider_config(
        "primary",
        retries=1,
        script=[
            {"exception": "rate_limit", "message": "slow"},
            {"output": "recovered"},
        ],
    )
    provider_b_config = _make_provider_config(
        "secondary",
        script=[{"output": "fallback"}],
    )
    provider_a = ScriptedProvider(provider_a_config)
    provider_b = ScriptedProvider(provider_b_config)
    providers = [(provider_a_config, provider_a), (provider_b_config, provider_b)]
    execution = _make_execution(providers, backoff=BackoffPolicy(rate_limit_sleep_s=0.05))
    sleep_calls: list[float] = []
    monkeypatch.setattr("adapter.core.runner_execution.time.sleep", lambda seconds: sleep_calls.append(seconds))
    task = _make_task()

    batch, _ = execution.run_sequential_attempt(providers, task, 0, "sequential")

    assert len(batch) == 1
    assert provider_a.call_count == 2
    assert provider_b.call_count == 0
    assert batch[0][1].metrics.status == "ok"
    assert sleep_calls == [0.05]


def test_provider_skip_moves_to_next_provider() -> None:
    provider_a_config = _make_provider_config(
        "skipper",
        script=[{"exception": "skip", "message": "temporary"}],
    )
    provider_b_config = _make_provider_config(
        "active",
        script=[{"output": "ok"}],
    )
    providers = [
        (provider_a_config, ScriptedProvider(provider_a_config)),
        (provider_b_config, ScriptedProvider(provider_b_config)),
    ]
    execution = _make_execution(providers)
    task = _make_task()

    batch, _ = execution.run_sequential_attempt(providers, task, 0, "sequential")

    assert len(batch) == 2
    assert batch[0][1].metrics.status == "skip"
    assert batch[1][1].metrics.status == "ok"


def test_compare_runner_all_failed_records_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = dict(ProviderFactory._registry)
    monkeypatch.setattr(ProviderFactory, "_registry", registry)
    registry["primary"] = ScriptedProvider
    registry["secondary"] = ScriptedProvider

    provider_a_config = _make_provider_config(
        "primary",
        retries=0,
        script=[{"exception": "auth", "message": "bad key"}],
    )
    provider_b_config = _make_provider_config(
        "secondary",
        retries=0,
        script=[{"exception": "retryable", "message": "flaky"}],
    )

    budget = BudgetBook(default=BudgetRule(1.0, 1.0, False), overrides={})
    runner = CompareRunner(
        [provider_a_config, provider_b_config],
        [_make_task()],
        BudgetManager(budget),
        metrics_path=tmp_path / "metrics.jsonl",
        runner_config=RunnerConfig(mode="sequential"),
    )
    config = RunnerConfig(mode="sequential", backoff=BackoffPolicy(retryable_next_provider=True))

    with pytest.raises(AllFailedError):
        runner.run(1, config)

    metrics_path = runner.metrics_path
    assert metrics_path.exists()
    lines = metrics_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    statuses = [payload["status"] for payload in payloads]
    assert statuses == ["error", "error"]
