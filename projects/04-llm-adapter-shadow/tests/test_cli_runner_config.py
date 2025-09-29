from __future__ import annotations

from dataclasses import replace

import pytest
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode


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
