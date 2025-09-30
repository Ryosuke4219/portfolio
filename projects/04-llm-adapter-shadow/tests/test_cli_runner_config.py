from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.llm_adapter import cli
from src.llm_adapter.runner import AsyncRunner, Runner
from src.llm_adapter.runner_config import (
    ConsensusStrategy,
    ConsensusTieBreaker,
    RunnerConfig,
    RunnerMode,
)
from src.llm_adapter.shadow import DEFAULT_METRICS_PATH


@pytest.mark.parametrize(
    ("mode_value", "expected"),
    [
        ("sequential", RunnerMode.SEQUENTIAL),
        ("parallel_any", RunnerMode.PARALLEL_ANY),
        ("parallel_all", RunnerMode.PARALLEL_ALL),
        ("consensus", RunnerMode.CONSENSUS),
    ],
)
def test_runner_config_normalizes_mode(
    mode_value: str, expected: RunnerMode
) -> None:
    config = RunnerConfig(mode=mode_value)
    assert config.mode is expected


def test_runner_config_accepts_enum_members() -> None:
    config = RunnerConfig(mode=RunnerMode.CONSENSUS)
    mutated = replace(config, mode=RunnerMode.SEQUENTIAL)
    assert mutated.mode is RunnerMode.SEQUENTIAL
    assert config.mode is RunnerMode.CONSENSUS


def test_cli_prepare_execution_with_consensus(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("hello world\n", encoding="utf-8")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{\"type\":\"object\"}", encoding="utf-8")
    metrics_path = tmp_path / "metrics.jsonl"

    args = cli.parse_args(
        [
            "--mode",
            "consensus",
            "--providers",
            "mock:fast,mock:slow",
            "--max-concurrency",
            "3",
            "--rpm",
            "120",
            "--aggregate",
            "max_score",
            "--quorum",
            "3",
            "--tie-breaker",
            "min_latency",
            "--schema",
            str(schema_path),
            "--judge",
            "pkg:judge",
            "--weights",
            "mock:fast=1.0,mock:slow=0.5",
            "--input",
            str(prompt_path),
            "--metrics",
            str(metrics_path),
        ]
    )

    assert args.providers == ("mock:fast", "mock:slow")
    assert args.weights == {"mock:fast": 1.0, "mock:slow": 0.5}

    runner, request, metrics = cli.prepare_execution(args)

    assert isinstance(runner, Runner)
    config = runner._config
    assert config.mode is RunnerMode.CONSENSUS
    consensus = config.consensus
    assert consensus is not None
    assert consensus.strategy is ConsensusStrategy.MAX_SCORE
    assert consensus.quorum == 3
    assert consensus.tie_breaker is ConsensusTieBreaker.MIN_LATENCY
    assert consensus.schema == schema_path.read_text(encoding="utf-8")
    assert consensus.judge == "pkg:judge"
    assert consensus.provider_weights == {"mock:fast": 1.0, "mock:slow": 0.5}
    assert metrics == str(metrics_path)
    assert request.prompt_text == "hello world"
    assert request.model == "fast"


def test_cli_prepare_execution_async(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("ping", encoding="utf-8")

    args = cli.parse_args(
        [
            "--mode",
            "parallel-any",
            "--providers",
            "mock:one",
            "--input",
            str(prompt_path),
            "--async-runner",
        ]
    )

    runner, request, metrics = cli.prepare_execution(args)

    assert isinstance(runner, AsyncRunner)
    assert runner._config.mode is RunnerMode.PARALLEL_ANY
    assert metrics == DEFAULT_METRICS_PATH
    assert request.model == "one"
