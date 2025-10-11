from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture()
def reloaded_runner_api():
    """Reload runner_api after ensuring src.* modules are absent."""

    for name in [
        "src",
        "src.llm_adapter",
        "src.llm_adapter.provider_spi",
        "adapter.core.runner_api",
    ]:
        sys.modules.pop(name, None)

    module = importlib.import_module("adapter.core.runner_api")

    import adapter.core.provider_spi as provider_spi

    assert module.ProviderSPI is provider_spi.ProviderSPI

    return SimpleNamespace(runner_api=module, provider_spi=provider_spi)


def test_run_compare_uses_adapter_provider_spi(
    reloaded_runner_api: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner_api = reloaded_runner_api.runner_api
    provider_spi = reloaded_runner_api.provider_spi

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

    captured_configs: list[Any] = []

    def fake_compare_runner(*args: Any, **kwargs: Any):
        captured_configs.append(kwargs["runner_config"])

        def _run(*call_args: Any, **run_kwargs: Any) -> list[int]:
            return []

        return SimpleNamespace(run=_run)

    monkeypatch.setattr(runner_api, "CompareRunner", fake_compare_runner)

    class DummyProvider(provider_spi.ProviderSPI):
        def name(self) -> str:
            return "dummy"

        def capabilities(self) -> set[str]:
            return {"test"}

        def invoke(self, request: Any) -> Any:
            return request

    result = runner_api.run_compare(
        [provider_path],
        prompt_path,
        budgets_path=budgets_path,
        metrics_path=metrics_path,
        shadow_provider=DummyProvider(),
    )

    assert result == 0
    assert captured_configs[-1].shadow_provider.__class__ is DummyProvider
