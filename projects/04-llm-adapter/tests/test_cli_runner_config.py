from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from adapter.cli import doctor
from adapter.core import runner_api
import adapter.run_compare as run_compare_module
from adapter.run_compare import RunnerMode


def test_parse_args_accepts_aggregate_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = tmp_path / "providers.yaml"
    provider.write_text("{}\n", encoding="utf-8")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("{}\n", encoding="utf-8")
    argv = [
        "run-compare",
        "--providers",
        str(provider),
        "--prompts",
        str(prompts),
        "--aggregate",
        "vote",
    ]
    monkeypatch.setattr(run_compare_module.argparse._sys, "argv", argv)

    parsed = run_compare_module._parse_args()

    assert parsed.aggregate == "vote"


def test_cli_main_passes_parallel_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = tmp_path / "providers.yaml"
    provider.write_text("{}\n", encoding="utf-8")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("{}\n", encoding="utf-8")
    args = SimpleNamespace(
        providers=str(provider),
        prompts=str(prompts),
        repeat=2,
        mode="parallel_any",
        budgets=None,
        metrics=None,
        log_level="DEBUG",
        allow_overrun=True,
        aggregate="weighted_vote",
        quorum=3,
        tie_breaker="min_cost",
        schema=None,
        judge=None,
        max_concurrency=4,
        rpm=90,
        weights="openai=1.5,anthropic=0.5",
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
    assert forwarded["aggregate"] == "weighted_vote"
    assert forwarded["tie_breaker"] == "min_cost"
    assert forwarded["provider_weights"] == {"openai": 1.5, "anthropic": 0.5}
    assert forwarded["mode"] is RunnerMode.PARALLEL_ANY
    assert RunnerMode.from_raw("parallel-any") is RunnerMode.PARALLEL_ANY


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
        "load_budget_book",
        lambda path: "book",
    )
    monkeypatch.setattr(
        runner_api,
        "load_golden_tasks",
        lambda path: ["task"],
    )
    monkeypatch.setattr(
        runner_api,
        "load_provider_configs",
        lambda paths: ["cfg"],
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
        provider_weights={"openai": 1.0},
    )
    assert captured["mode"] is runner_api.RunnerMode.PARALLEL_ANY
    assert captured["mode"].value.replace("-", "_") == "parallel_any"
    assert captured["quorum"] == 5
    assert captured["max_concurrency"] is None
    assert captured["rpm"] is None
    assert isinstance(captured["backoff"], runner_api.BackoffPolicy)
    assert captured["backoff"].rate_limit_sleep_s is None
    assert captured["shadow_provider"] is None
    assert captured["provider_weights"] is None
    assert captured["metrics_path"].name == "metrics.jsonl"
    assert captured["repeat"] == 1


def test_main_requires_weights_for_weighted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = tmp_path / "providers.yaml"
    provider.write_text("{}\n", encoding="utf-8")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("{}\n", encoding="utf-8")
    args = SimpleNamespace(
        providers=str(provider),
        prompts=str(prompts),
        repeat=1,
        mode="sequential",
        budgets=None,
        metrics=None,
        log_level="INFO",
        allow_overrun=False,
        aggregate="weighted",
        quorum=None,
        tie_breaker=None,
        schema=None,
        judge=None,
        max_concurrency=None,
        rpm=None,
        weights=None,
    )
    monkeypatch.setattr(run_compare_module, "_parse_args", lambda: args)

    with pytest.raises(SystemExit, match="weighted_vote"):
        run_compare_module.main()


def test_main_rejects_weights_for_non_weighted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = tmp_path / "providers.yaml"
    provider.write_text("{}\n", encoding="utf-8")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("{}\n", encoding="utf-8")
    args = SimpleNamespace(
        providers=str(provider),
        prompts=str(prompts),
        repeat=1,
        mode="sequential",
        budgets=None,
        metrics=None,
        log_level="INFO",
        allow_overrun=False,
        aggregate="max_score",
        quorum=None,
        tie_breaker=None,
        schema=None,
        judge=None,
        max_concurrency=None,
        rpm=None,
        weights="openai=1.0",
    )
    monkeypatch.setattr(run_compare_module, "_parse_args", lambda: args)

    with pytest.raises(SystemExit, match="--weights は aggregate=weighted_vote"):
        run_compare_module.main()


def test_doctor_windows_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.sys, "platform", "win32")

    class DummyStream:
        def __init__(self, encoding: str | None) -> None:
            self.encoding = encoding

    monkeypatch.setattr(doctor.sys, "stdout", DummyStream("UTF-8"))
    monkeypatch.setattr(doctor.sys, "stdin", DummyStream("utf-8"))

    name, status, detail = doctor._doctor_check_windows_encoding("ja")
    assert name == "doctor_name_windows"
    assert status == "ok"
    assert detail == "stdout=utf-8, stdin=utf-8"
