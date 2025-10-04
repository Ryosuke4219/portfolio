from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapter.core.datasets import GoldenTask
from adapter.core.errors import TimeoutError
from adapter.core.metrics import BudgetSnapshot, RunMetrics
from adapter.core.models import ProviderConfig
from adapter.core.providers import BaseProvider, ProviderFactory, ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import RunnerExecution
from adapter.core.runners import CompareRunner

from ._sys_path import BudgetManager
from .conftest import ProviderConfigFactory, RunMetricsFactory, TaskFactory


def test_runner_execution_records_shadow_budget_and_schema(
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    run_metrics_factory: RunMetricsFactory,
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
        golden_task: GoldenTask,
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


def test_runner_config_dataclass_initializes_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory: Callable[[], BudgetManager],
) -> None:
    token_bucket_args: list[int | None] = []
    schema_args: list[Path | None] = []

    class RecordingTokenBucket:
        def __init__(self, rpm: int | None) -> None:
            token_bucket_args.append(rpm)

        def acquire(self) -> None:
            return None

    class RecordingSchemaValidator:
        def __init__(self, schema: Path | None) -> None:
            schema_args.append(schema)

        def validate(self, payload: str) -> None:
            return None

    from adapter.core import runners as runners_module

    monkeypatch.setattr(runners_module, "_TokenBucket", RecordingTokenBucket)
    monkeypatch.setattr(runners_module, "_SchemaValidator", RecordingSchemaValidator)

    class SingleCallProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="ok", input_tokens=1, output_tokens=1, latency_ms=1)

    monkeypatch.setitem(ProviderFactory._registry, "single", SingleCallProvider)

    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    runner = CompareRunner(
        [provider_config_factory(tmp_path, name="single", provider="single", model="model")],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_helpers.jsonl",
    )
    config = RunnerConfig(mode="sequential", rpm=3, schema=schema_path)

    runner.run(repeat=1, config=config)

    assert token_bucket_args == [3]
    assert schema_args == [schema_path]


def test_run_metrics_records_error_type_and_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory: Callable[[], BudgetManager],
) -> None:
    class FlakyProvider(BaseProvider):
        def __init__(self, config: ProviderConfig) -> None:
            super().__init__(config)
            self.calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("boom")
            return ProviderResponse(output_text="flaky-ok", input_tokens=1, output_tokens=1, latency_ms=5)

    class StableProvider(BaseProvider):
        def __init__(self, config: ProviderConfig) -> None:
            super().__init__(config)

        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="stable-ok", input_tokens=1, output_tokens=1, latency_ms=2)

    monkeypatch.setitem(ProviderFactory._registry, "flaky", FlakyProvider)
    monkeypatch.setitem(ProviderFactory._registry, "stable", StableProvider)

    runner = CompareRunner(
        [
            provider_config_factory(tmp_path, name="flaky", provider="flaky", model="F"),
            provider_config_factory(tmp_path, name="stable", provider="stable", model="S"),
        ],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_attempts.jsonl",
    )
    results = runner.run(repeat=2, config=RunnerConfig(mode="parallel_all"))

    flaky_attempts = {
        metric.attempts: metric for metric in results if metric.provider == "flaky"
    }
    stable_attempts = sorted(
        (metric.attempts, metric.error_type)
        for metric in results
        if metric.provider == "stable"
    )

    assert flaky_attempts[1].status == "error"
    assert flaky_attempts[1].error_type == "TimeoutError"
    assert flaky_attempts[2].status == "ok"
    assert flaky_attempts[2].error_type is None
    assert stable_attempts == [(1, None), (2, None)]
