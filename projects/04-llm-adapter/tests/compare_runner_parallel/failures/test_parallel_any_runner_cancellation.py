from __future__ import annotations

import time
from pathlib import Path

import pytest

from adapter.core.providers import BaseProvider, ProviderResponse

from .common import ProviderSetup, create_runner, run_parallel_any
from tests.compare_runner_parallel.conftest import (
    ProviderConfigFactory,
    TaskFactory,
)


def test_parallel_any_cancels_pending_workers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
) -> None:
    class FastProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="fast", input_tokens=1, output_tokens=1, latency_ms=1)

    class SlowProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            time.sleep(0.05)
            return ProviderResponse(output_text="slow", input_tokens=1, output_tokens=1, latency_ms=50)

    runner = create_runner(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        provider_config_factory=provider_config_factory,
        task_factory=task_factory,
        budget_manager_factory=budget_manager_factory,
        providers=[
            ProviderSetup(
                registry_name="fast",
                config_name="fast",
                model_name="fast",
                provider_cls=FastProvider,
            ),
            ProviderSetup(
                registry_name="slow",
                config_name="slow",
                model_name="slow",
                provider_cls=SlowProvider,
            ),
        ],
        metrics_filename="metrics_cancel.jsonl",
    )

    try:
        results = run_parallel_any(runner)
    except Exception as exc:  # pragma: no cover - defensive guard
        pytest.fail(f"ParallelExecutionError was raised unexpectedly: {exc}")

    assert {metric.model: metric.status for metric in results} == {"fast": "ok", "slow": "skip"}
    slow_metric = next(metric for metric in results if metric.model == "slow")
    assert slow_metric.failure_kind == "cancelled"
    assert slow_metric.error_message is not None
