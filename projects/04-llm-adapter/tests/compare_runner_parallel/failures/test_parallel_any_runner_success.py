from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core.providers import BaseProvider, ProviderResponse
from adapter.core.runners import CompareRunner
from tests.compare_runner_parallel.conftest import (
    ProviderConfigFactory,
    TaskFactory,
)

from .common import (
    create_runner,
    patch_run_parallel_any_first,
    ProviderSetup,
    run_parallel_any,
)


def _create_runner(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
    providers: list[ProviderSetup],
    metrics_filename: str,
) -> CompareRunner:
    patch_run_parallel_any_first(monkeypatch)
    return create_runner(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        budget_manager_factory=budget_manager_factory,
        providers=providers,
        metrics_filename=metrics_filename,
    )


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
            return ProviderResponse(
                output_text=self.config.model,
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    runner = _create_runner(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        budget_manager_factory=budget_manager_factory,
        providers=[
            ProviderSetup(
                registry_name="recording",
                config_name="fast",
                model_name="fast",
                provider_cls=RecordingProvider,
            ),
            ProviderSetup(
                registry_name="recording",
                config_name="slow",
                model_name="slow",
                provider_cls=RecordingProvider,
            ),
        ],
        metrics_filename="metrics_any.jsonl",
    )

    try:
        results = run_parallel_any(runner)
    except Exception as exc:  # pragma: no cover - defensive guard
        pytest.fail(f"ParallelExecutionError was raised unexpectedly: {exc}")

    assert {metric.model: metric.status for metric in results} == {
        "fast": "ok",
        "slow": "skip",
    }
    assert calls == ["fast"]


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
            return ProviderResponse(
                output_text="winner",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
            )

    class IdleProvider(BaseProvider):
        called = False

        def generate(self, prompt: str) -> ProviderResponse:  # pragma: no cover - guard
            IdleProvider.called = True
            raise AssertionError("idle provider should not run")

    runner = _create_runner(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        budget_manager_factory=budget_manager_factory,
        providers=[
            ProviderSetup(
                registry_name="winner",
                config_name="winner",
                model_name="winner",
                provider_cls=WinnerProvider,
            ),
            ProviderSetup(
                registry_name="idle",
                config_name="idle",
                model_name="idle",
                provider_cls=IdleProvider,
            ),
        ],
        metrics_filename="metrics_unscheduled.jsonl",
    )

    try:
        results = run_parallel_any(runner)
    except Exception as exc:  # pragma: no cover - defensive guard
        pytest.fail(f"ParallelExecutionError was raised unexpectedly: {exc}")

    metrics_by_model = {metric.model: metric for metric in results}
    assert WinnerProvider.calls == 1
    assert IdleProvider.called is False

    idle_metrics = metrics_by_model["idle"]
    assert idle_metrics.status == "skip"
    assert idle_metrics.failure_kind == "cancelled"
    assert idle_metrics.error_message is not None
    assert idle_metrics.input_tokens == 0
    assert idle_metrics.output_tokens == 0
    assert idle_metrics.latency_ms == 0
    assert idle_metrics.cost_usd == pytest.approx(0.0)

    winner_metrics = metrics_by_model["winner"]
    assert winner_metrics.status == "ok"
    assert winner_metrics.failure_kind is None
    assert winner_metrics.error_message is None
