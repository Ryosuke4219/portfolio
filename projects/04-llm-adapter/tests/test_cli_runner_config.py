from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from adapter import run_compare as run_compare_module
from adapter.core import runner_api


def test_cli_main_passes_parallel_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = tmp_path / "providers.yaml"
    provider.write_text("{}\n", encoding="utf-8")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("{}\n", encoding="utf-8")
    args = SimpleNamespace(
        providers=str(provider),
        prompts=str(prompts),
        repeat=2,
        mode="parallel-any",
        budgets=None,
        metrics=None,
        log_level="DEBUG",
        allow_overrun=True,
        aggregate=None,
        quorum=3,
        tie_breaker=None,
        schema=None,
        judge=None,
        max_concurrency=4,
        rpm=90,
    )
    monkeypatch.setattr(run_compare_module, "_parse_args", lambda: args)
    captured: dict[str, object] = {}

    def fake_run_compare(provider_paths: list[Path], prompt_path: Path, **kwargs: object) -> int:
        captured["providers"] = provider_paths
        captured["prompt"] = prompt_path
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(run_compare_module.runner_api, "run_compare", fake_run_compare)
    assert run_compare_module.main() == 0
    assert [p.name for p in captured["providers"]] == ["providers.yaml"]
    assert captured["prompt"].name == "prompts.jsonl"
    forwarded = captured["kwargs"]
    assert forwarded["max_concurrency"] == 4
    assert forwarded["quorum"] == 3
    assert forwarded["rpm"] == 90


def test_run_compare_sanitizes_runner_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider_path = tmp_path / "p.yaml"
    prompt_path = tmp_path / "prompts.jsonl"
    provider_path.write_text("{}\n", encoding="utf-8")
    prompt_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        runner_api,
        "load_provider_configs",
        lambda paths: ["cfg"],
    )
    monkeypatch.setattr(
        runner_api,
        "load_golden_tasks",
        lambda path: ["task"],
    )
    monkeypatch.setattr(
        runner_api,
        "load_budget_book",
        lambda path: "book",
    )
    monkeypatch.setattr(runner_api, "BudgetManager", lambda book: "budget")
    captured: dict[str, object] = {}

    class DummyRunner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def run(self, *, repeat: int, mode: str) -> list[str]:
            captured["repeat"] = repeat
            captured["mode"] = mode
            return []

    monkeypatch.setattr(runner_api, "CompareRunner", lambda *_a, **_k: DummyRunner())

    class DummyConfig:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.mode = kwargs["mode"]

    monkeypatch.setattr(runner_api, "RunnerConfig", DummyConfig)
    runner_api.run_compare(
        [provider_path],
        prompt_path,
        budgets_path=tmp_path / "budgets.yaml",
        metrics_path=tmp_path / "metrics.jsonl",
        repeat=0,
        mode="parallel-any",
        quorum=5,
        max_concurrency=-1,
        rpm=0,
    )
    assert captured["mode"] == "parallel-any"
    assert captured["quorum"] == 5
    assert captured["max_concurrency"] is None
    assert captured["rpm"] is None
    assert captured["repeat"] == 1
