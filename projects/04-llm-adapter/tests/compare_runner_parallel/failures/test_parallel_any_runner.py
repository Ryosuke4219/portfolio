from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from adapter.core import _parallel_shim, errors
from adapter.core.config import ProviderConfig
from adapter.core.errors import AuthError, ConfigError, ProviderSkip, TimeoutError
from adapter.core.metrics.models import BudgetSnapshot, RunMetrics
from adapter.core.providers import BaseProvider, ProviderFactory, ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import RunnerExecution
from adapter.core.runners import CompareRunner
from tests.compare_runner_parallel.conftest import (
    ProviderConfigFactory,
    RunMetricsFactory,
    TaskFactory,
)


def _normalize_mode(value: str) -> str:
    return value.replace("-", "_")


def test_parallel_any_stops_after_first_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> None:
    calls: list[str] = []

    class RecordingProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            calls.append(self.config.model)
            return ProviderResponse(output_text=self.config.model, input_tokens=1, output_tokens=1, latency_ms=5)

    monkeypatch.setitem(ProviderFactory._registry, "recording", RecordingProvider)

    fast_config = provider_config_factory(tmp_path, name="fast", provider="recording", model="fast")
    slow_config = provider_config_factory(tmp_path, name="slow", provider="recording", model="slow")

    from adapter.core import runners as runners_module

    def fake_run_parallel_any(workers, *, max_concurrency=None):  # type: ignore[override]
        return workers[0]()

    monkeypatch.setattr(runners_module, "run_parallel_any_sync", fake_run_parallel_any)

    runner = CompareRunner(
        [fast_config, slow_config],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_any.jsonl",
    )
    try:
        results = runner.run(
            repeat=1,
            config=RunnerConfig(mode="parallel_any", max_concurrency=2),
        )
    except (errors.ParallelExecutionError, _parallel_shim.ParallelExecutionError) as exc:
        pytest.fail(f"ParallelExecutionError was raised unexpectedly: {exc}")
    assert {metric.model: metric.status for metric in results} == {"fast": "ok", "slow": "skip"}
    assert calls == ["fast"]


def test_parallel_any_cancels_pending_workers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> None:
    import time

    class FastProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="fast", input_tokens=1, output_tokens=1, latency_ms=1)

    class SlowProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            time.sleep(0.05)
            return ProviderResponse(output_text="slow", input_tokens=1, output_tokens=1, latency_ms=50)

    monkeypatch.setitem(ProviderFactory._registry, "fast", FastProvider)
    monkeypatch.setitem(ProviderFactory._registry, "slow", SlowProvider)

    fast_config = provider_config_factory(tmp_path, name="fast", provider="fast", model="fast")
    slow_config = provider_config_factory(tmp_path, name="slow", provider="slow", model="slow")

    runner = CompareRunner(
        [fast_config, slow_config],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_cancel.jsonl",
    )
    try:
        results = runner.run(
            repeat=1,
            config=RunnerConfig(mode="parallel_any", max_concurrency=2),
        )
    except (errors.ParallelExecutionError, _parallel_shim.ParallelExecutionError) as exc:
        pytest.fail(f"ParallelExecutionError was raised unexpectedly: {exc}")

    assert {metric.model: metric.status for metric in results} == {"fast": "ok", "slow": "skip"}
    slow_metric = next(metric for metric in results if metric.model == "slow")
    assert slow_metric.failure_kind == "cancelled"
    assert _normalize_mode(slow_metric.error_message or "") == "parallel_any cancelled after winner"


def test_parallel_any_populates_metrics_for_unscheduled_workers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> None:
    class WinnerProvider(BaseProvider):
        calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            WinnerProvider.calls += 1
            return ProviderResponse(output_text="winner", input_tokens=1, output_tokens=1, latency_ms=5)

    class IdleProvider(BaseProvider):
        called = False

        def generate(self, prompt: str) -> ProviderResponse:  # pragma: no cover - guard
            IdleProvider.called = True
            raise AssertionError("idle provider should not run")

    monkeypatch.setitem(ProviderFactory._registry, "winner", WinnerProvider)
    monkeypatch.setitem(ProviderFactory._registry, "idle", IdleProvider)

    winner_config = provider_config_factory(tmp_path, name="winner", provider="winner", model="winner")
    idle_config = provider_config_factory(tmp_path, name="idle", provider="idle", model="idle")

    from adapter.core import runners as runners_module

    def fake_run_parallel_any(workers, *, max_concurrency=None):  # type: ignore[override]
        return workers[0]()

    monkeypatch.setattr(runners_module, "run_parallel_any_sync", fake_run_parallel_any)

    runner = CompareRunner(
        [winner_config, idle_config],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_unscheduled.jsonl",
    )
    try:
        results = runner.run(
            repeat=1,
            config=RunnerConfig(mode="parallel_any", max_concurrency=2),
        )
    except (errors.ParallelExecutionError, _parallel_shim.ParallelExecutionError) as exc:
        pytest.fail(f"ParallelExecutionError was raised unexpectedly: {exc}")

    metrics_by_model = {metric.model: metric for metric in results}
    assert WinnerProvider.calls == 1
    assert IdleProvider.called is False

    idle_metrics = metrics_by_model["idle"]
    assert idle_metrics.status == "skip"
    assert idle_metrics.failure_kind == "cancelled"
    assert _normalize_mode(idle_metrics.error_message or "") == "parallel_any cancelled after winner"
    assert idle_metrics.input_tokens == 0
    assert idle_metrics.output_tokens == 0
    assert idle_metrics.latency_ms == 0
    assert idle_metrics.cost_usd == 0.0


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


def test_parallel_any_failure_summary_includes_all_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> None:
    class SkipProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            raise ProviderSkip("skip me")

    class TimeoutProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            raise TimeoutError("deadline")

    monkeypatch.setitem(ProviderFactory._registry, "skip", SkipProvider)
    monkeypatch.setitem(ProviderFactory._registry, "timeout", TimeoutProvider)

    skip_config = provider_config_factory(tmp_path, name="skip", provider="skip", model="skip-model")
    timeout_config = provider_config_factory(tmp_path, name="timeout", provider="timeout", model="timeout-model")

    runner = CompareRunner(
        [skip_config, timeout_config],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_failure_summary.jsonl",
    )

    with pytest.raises((errors.ParallelExecutionError, _parallel_shim.ParallelExecutionError)) as exc_info:
        runner.run(repeat=1, config=RunnerConfig(mode="parallel_any", max_concurrency=2))

    failures = getattr(exc_info.value, "failures", ())
    assert len(failures) == 2
    summary_by_provider = {failure.provider: failure for failure in failures}

    skip_summary = summary_by_provider["skip"]
    assert skip_summary.status == "skip"
    assert skip_summary.failure_kind == "skip"
    assert skip_summary.error_message == "skip me"
    assert skip_summary.backoff_next_provider is True
    assert skip_summary.retries == 0
    assert skip_summary.error_type == "ProviderSkip"

    timeout_summary = summary_by_provider["timeout"]
    assert timeout_summary.status == "error"
    assert timeout_summary.failure_kind == "timeout"
    assert timeout_summary.error_message == "deadline"
    assert timeout_summary.backoff_next_provider is False
    assert timeout_summary.retries == 0
    assert timeout_summary.error_type == "TimeoutError"
