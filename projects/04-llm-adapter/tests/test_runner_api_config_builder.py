from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from adapter.core import runner_api
from adapter.core.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from adapter.core.runner_config_builder import RunnerConfig, RunnerMode


class _ShadowProvider(ProviderSPI):
    def name(self) -> str:
        return "shadow"

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


@pytest.fixture()
def run_compare_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    provider_path = tmp_path / "provider.yaml"
    provider_path.write_text("provider: test\n")
    prompt_path = tmp_path / "tasks.jsonl"
    prompt_path.write_text("{}\n")
    budgets_path = tmp_path / "budgets.yaml"
    budgets_path.write_text("{}\n")
    metrics_path = tmp_path / "metrics.jsonl"

    monkeypatch.setattr(runner_api, "load_provider_configs", lambda _: ["cfg"])
    monkeypatch.setattr(runner_api, "load_golden_tasks", lambda _: ["task"])
    monkeypatch.setattr(runner_api, "load_budget_book", lambda _: {"budget": 1})
    monkeypatch.setattr(runner_api, "BudgetManager", lambda _: SimpleNamespace())

    captured_configs: list[RunnerConfig] = []
    run_calls: list[dict[str, Any]] = []

    def fake_compare_runner(*args: Any, **kwargs: Any):
        captured_configs.append(kwargs["runner_config"])

        def _run(*call_args: Any, **run_kwargs: Any) -> list[int]:
            run_calls.append({"args": call_args, "kwargs": run_kwargs})
            return []

        return SimpleNamespace(run=_run)

    monkeypatch.setattr(runner_api, "CompareRunner", fake_compare_runner)

    return SimpleNamespace(
        provider_paths=[provider_path],
        prompt_path=prompt_path,
        budgets_path=budgets_path,
        metrics_path=metrics_path,
        captured=captured_configs,
        run_calls=run_calls,
    )


def test_run_compare_ignores_weights_without_weighted_aggregate(
    run_compare_env: SimpleNamespace,
) -> None:
    env = run_compare_env

    assert (
        runner_api.run_compare(
            env.provider_paths,
            env.prompt_path,
            budgets_path=env.budgets_path,
            metrics_path=env.metrics_path,
            provider_weights=None,
        )
        == 0
    )
    assert env.captured[-1].provider_weights is None

    assert (
        runner_api.run_compare(
            env.provider_paths,
            env.prompt_path,
            budgets_path=env.budgets_path,
            metrics_path=env.metrics_path,
            provider_weights={"a": 0.5},
        )
        == 0
    )
    assert env.captured[-1].provider_weights is None
    assert len(env.run_calls) == 2


def test_run_compare_overrides_metrics_and_shadow(
    run_compare_env: SimpleNamespace,
) -> None:
    env = run_compare_env
    shadow = _ShadowProvider()
    base_config = RunnerConfig(mode=RunnerMode.SEQUENTIAL)

    result = runner_api.run_compare(
        env.provider_paths,
        env.prompt_path,
        budgets_path=env.budgets_path,
        metrics_path=env.metrics_path,
        runner_config=base_config,
        shadow_provider=shadow,
    )
    assert result == 0
    config = env.captured[-1]
    assert config.metrics_path == env.metrics_path
    assert config.shadow_provider is shadow


def test_run_compare_passes_repeat_then_config(
    run_compare_env: SimpleNamespace,
) -> None:
    env = run_compare_env

    repeat = 3
    result = runner_api.run_compare(
        env.provider_paths,
        env.prompt_path,
        budgets_path=env.budgets_path,
        metrics_path=env.metrics_path,
        repeat=repeat,
    )

    assert result == 0
    assert env.run_calls[-1]["args"] == (repeat, env.captured[-1])
    assert env.run_calls[-1]["kwargs"] == {}
