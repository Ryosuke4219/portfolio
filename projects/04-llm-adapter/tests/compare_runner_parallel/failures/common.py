from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

from adapter.core.metrics.models import RunMetrics
from adapter.core.providers import BaseProvider, ProviderFactory
from adapter.core.runner_api import RunnerConfig
from adapter.core.runners import CompareRunner

from tests.compare_runner_parallel.conftest import (
    ProviderConfigFactory,
    TaskFactory,
)


@dataclass(frozen=True, slots=True)
class ProviderSetup:
    registry_name: str
    config_name: str
    model_name: str
    provider_cls: type[BaseProvider]


def _register_providers(
    monkeypatch: pytest.MonkeyPatch,
    providers: Iterable[ProviderSetup],
) -> None:
    registered: set[str] = set()
    for provider in providers:
        if provider.registry_name in registered:
            continue
        monkeypatch.setitem(
            ProviderFactory._registry,
            provider.registry_name,
            provider.provider_cls,
        )
        registered.add(provider.registry_name)


def create_runner(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: ProviderConfigFactory,
    task_factory: TaskFactory,
    budget_manager_factory,
    providers: Iterable[ProviderSetup],
    metrics_filename: str,
) -> CompareRunner:
    provider_list = list(providers)
    _register_providers(monkeypatch, provider_list)
    configs = [
        provider_config_factory(
            tmp_path,
            name=provider.config_name,
            provider=provider.registry_name,
            model=provider.model_name,
        )
        for provider in provider_list
    ]
    return CompareRunner(
        configs,
        [task_factory()],
        budget_manager_factory(),
        tmp_path / metrics_filename,
    )


def patch_run_parallel_any_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter.core import runners as runners_module

    def fake_run_parallel_any(workers, *, max_concurrency=None):  # type: ignore[override]
        return workers[0]()

    monkeypatch.setattr(runners_module, "run_parallel_any_sync", fake_run_parallel_any)


def run_parallel_any(
    runner: CompareRunner,
    *,
    max_concurrency: int = 2,
) -> list[RunMetrics]:
    return runner.run(
        repeat=1,
        config=RunnerConfig(mode="parallel_any", max_concurrency=max_concurrency),
    )


__all__ = [
    "ProviderSetup",
    "create_runner",
    "patch_run_parallel_any_first",
    "run_parallel_any",
]
