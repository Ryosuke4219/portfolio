from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from adapter.core.providers import BaseProvider, ProviderFactory, ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runners import CompareRunner

if TYPE_CHECKING:
    from tests.compare_runner_parallel.conftest import ProviderConfigFactory, TaskFactory


def _register_provider(monkeypatch: pytest.MonkeyPatch, name: str, cls: type[BaseProvider]) -> None:
    monkeypatch.setitem(ProviderFactory._registry, name, cls)


def _run_consensus(
    tmp_path: Path,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    budget_manager_factory,
    provider_specs: list[tuple[str, str, str]],
    *,
    metrics_name: str,
    **config_kwargs,
):
    configs = [
        provider_config_factory(tmp_path, name=name, provider=provider, model=model)
        for name, provider, model in provider_specs
    ]
    runner = CompareRunner(
        configs,
        [task_factory()],
        budget_manager_factory(),
        tmp_path / metrics_name,
    )
    return runner.run(repeat=1, config=RunnerConfig(mode="consensus", **config_kwargs))


def test_consensus_default_quorum_meta_uses_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    budget_manager_factory,
) -> None:
    class ThreeWayConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="YES", input_tokens=1, output_tokens=1, latency_ms=5)

    _register_provider(monkeypatch, "three-way-consensus", ThreeWayConsensusProvider)

    results = _run_consensus(
        tmp_path,
        provider_config_factory,
        task_factory,
        budget_manager_factory,
        [
            ("p1", "three-way-consensus", "YES"),
            ("p2", "three-way-consensus", "YES"),
            ("p3", "three-way-consensus", "YES"),
        ],
        metrics_name="metrics_consensus_quorum_default.jsonl",
    )
    winner = next(metric for metric in results if metric.ci_meta.get("consensus"))
    assert winner.ci_meta["consensus"]["quorum"] == 2
    assert winner.ci_meta["aggregate_quorum"] == 2


def test_consensus_quorum_failure_marks_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    budget_manager_factory,
) -> None:
    class ConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="YES", input_tokens=1, output_tokens=1, latency_ms=5)

    _register_provider(monkeypatch, "consensus", ConsensusProvider)

    runner = CompareRunner(
        [
            provider_config_factory(tmp_path, name="c1", provider="consensus", model="M1"),
            provider_config_factory(tmp_path, name="c2", provider="consensus", model="M2"),
        ],
        [task_factory()],
        budget_manager_factory(),
        tmp_path / "metrics_quorum.jsonl",
    )
    results = runner.run(repeat=2, config=RunnerConfig(mode="consensus", quorum=3))
    assert len(results) == 4
    for metric in results:
        assert metric.status == "error"
        assert metric.failure_kind == "consensus_quorum"
        assert metric.error_message and "quorum" in metric.error_message
        assert "aggregate_strategy" not in metric.ci_meta
        assert metric.ci_meta["aggregate_mode"] == "consensus"
        assert metric.ci_meta["aggregate_quorum"] == 3
        assert metric.ci_meta["aggregate_votes"] == 2


def test_consensus_quorum_falls_back_to_judge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    budget_manager_factory,
) -> None:
    class ConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            return ProviderResponse(output_text="YES", input_tokens=1, output_tokens=1, latency_ms=5)

    class JudgeProvider(BaseProvider):
        calls = 0

        def generate(self, prompt: str) -> ProviderResponse:
            JudgeProvider.calls += 1
            return ProviderResponse(output_text="JUDGE", input_tokens=1, output_tokens=1, latency_ms=5)

    _register_provider(monkeypatch, "consensus", ConsensusProvider)
    _register_provider(monkeypatch, "judge-consensus", JudgeProvider)

    judge_config = provider_config_factory(
        tmp_path, name="judge", provider="judge-consensus", model="judge-model"
    )
    results = _run_consensus(
        tmp_path,
        provider_config_factory,
        task_factory,
        budget_manager_factory,
        [
            ("c1", "consensus", "A"),
            ("c2", "consensus", "A"),
        ],
        metrics_name="metrics_consensus_quorum_fallback.jsonl",
        quorum=3,
        judge_provider=judge_config,
    )
    winner = next(metric for metric in results if metric.ci_meta.get("aggregate_strategy") == "judge")
    assert winner.status == "ok"
    assert winner.failure_kind is None
    assert winner.ci_meta["aggregate_mode"] == "consensus"
    assert winner.ci_meta["aggregate_quorum"] == 3
    assert winner.ci_meta["consensus"]["fallback"] == "judge"
    assert JudgeProvider.calls == 1
    assert all(metric.failure_kind != "consensus_quorum" for metric in results)


def test_consensus_default_quorum_requires_two_votes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_config_factory: "ProviderConfigFactory",
    task_factory: "TaskFactory",
    budget_manager_factory,
) -> None:
    class SplitConsensusProvider(BaseProvider):
        def generate(self, prompt: str) -> ProviderResponse:
            latency = 1 if self.config.model == "A" else 5
            return ProviderResponse(output_text=self.config.model, input_tokens=1, output_tokens=1, latency_ms=latency)

    _register_provider(monkeypatch, "split-consensus", SplitConsensusProvider)

    results = _run_consensus(
        tmp_path,
        provider_config_factory,
        task_factory,
        budget_manager_factory,
        [
            ("p1", "split-consensus", "A"),
            ("p2", "split-consensus", "B"),
        ],
        metrics_name="metrics_quorum_default.jsonl",
    )
    assert len(results) == 2
    for metric in results:
        assert metric.status == "error"
        assert metric.failure_kind == "consensus_quorum"
        assert metric.ci_meta["aggregate_mode"] == "consensus"
        assert metric.ci_meta["aggregate_quorum"] == 2
        assert metric.ci_meta["aggregate_votes"] == 1
        assert "aggregate_strategy" not in metric.ci_meta
