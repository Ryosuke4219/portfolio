from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from src.llm_adapter import cli
from src.llm_adapter.runner import AsyncRunner, Runner
from src.llm_adapter.runner_config import (
    ConsensusConfig,
    DEFAULT_MAX_CONCURRENCY,
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


def test_runner_config_validates_max_concurrency_and_metrics_path(tmp_path: Path) -> None:
    metrics_path = tmp_path / "custom.jsonl"
    config = RunnerConfig(metrics_path=metrics_path)
    assert config.max_concurrency == DEFAULT_MAX_CONCURRENCY
    assert config.metrics_path == metrics_path
    with pytest.raises(ValueError):
        RunnerConfig(max_concurrency=0)


def test_consensus_config_defaults() -> None:
    config = ConsensusConfig()
    assert config.strategy == "majority_vote"
    assert config.quorum == 2


def test_build_runner_config_uses_defaults(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("payload", encoding="utf-8")

    args = cli.parse_args(
        [
            "--mode",
            "sequential",
            "--providers",
            "mock:primary",
            "--input",
            str(prompt_path),
        ]
    )

    config = cli.build_runner_config(args)

    assert config == RunnerConfig(mode=RunnerMode.SEQUENTIAL)
    assert config.max_concurrency == DEFAULT_MAX_CONCURRENCY
    assert config.metrics_path == DEFAULT_METRICS_PATH


def test_build_runner_config_with_overrides(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("payload", encoding="utf-8")
    metrics_path = tmp_path / "metrics.jsonl"

    args = cli.parse_args(
        [
            "--mode",
            "parallel-all",
            "--providers",
            "mock:one,mock:two",
            "--input",
            str(prompt_path),
            "--max-concurrency",
            "2",
            "--rpm",
            "90",
            "--metrics",
            str(metrics_path),
        ]
    )

    config = cli.build_runner_config(args)

    assert config == RunnerConfig(
        mode=RunnerMode.PARALLEL_ALL,
        max_concurrency=2,
        rpm=90,
        metrics_path=metrics_path,
    )


def test_build_runner_config_with_consensus(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("payload", encoding="utf-8")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    args = cli.parse_args(
        [
            "--mode",
            "consensus",
            "--providers",
            "mock:alpha,mock:beta",
            "--input",
            str(prompt_path),
            "--aggregate",
            "weighted_vote",
            "--quorum",
            "3",
            "--tie-breaker",
            "min_latency",
            "--schema",
            str(schema_path),
        ]
    )

    config = cli.build_runner_config(args)

    assert config.mode is RunnerMode.CONSENSUS
    assert config.max_concurrency == DEFAULT_MAX_CONCURRENCY
    assert config.metrics_path == DEFAULT_METRICS_PATH
    assert config.consensus == ConsensusConfig(
        strategy="weighted_vote",
        quorum=3,
        tie_breaker="min_latency",
        schema="{}",
    )


def test_build_runner_config_with_consensus_constraints(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("payload", encoding="utf-8")

    args = cli.parse_args(
        [
            "--mode",
            "consensus",
            "--providers",
            "mock:alpha,mock:beta",
            "--input",
            str(prompt_path),
            "--max-latency-ms",
            "250",
            "--max-cost-usd",
            "1.75",
        ]
    )

    config = cli.build_runner_config(args)

    assert config.consensus == ConsensusConfig(
        max_latency_ms=250,
        max_cost_usd=1.75,
    )


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
    assert consensus.strategy == "max_score"
    assert consensus.quorum == 3
    assert consensus.tie_breaker == "min_latency"
    assert consensus.schema == schema_path.read_text(encoding="utf-8")
    assert consensus.judge == "pkg:judge"
    assert consensus.provider_weights == {"mock:fast": 1.0, "mock:slow": 0.5}
    assert metrics == str(metrics_path)
    assert config.metrics_path == metrics_path
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


def test_cli_prepare_execution_uses_defaults(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("ping", encoding="utf-8")

    args = cli.parse_args(
        [
            "--mode",
            "sequential",
            "--providers",
            "mock:primary",
            "--input",
            str(prompt_path),
        ]
    )

    runner, _request, metrics = cli.prepare_execution(args)
    assert runner._config.max_concurrency == DEFAULT_MAX_CONCURRENCY
    assert runner._config.metrics_path == DEFAULT_METRICS_PATH
    assert metrics == DEFAULT_METRICS_PATH
