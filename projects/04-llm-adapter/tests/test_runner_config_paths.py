"""RunnerConfig path normalization tests."""

from pathlib import Path

from adapter.core.runner_api import RunnerConfig


def test_metrics_path_accepts_str_and_normalizes_to_path() -> None:
    config = RunnerConfig(mode="sequential", metrics_path="runs.jsonl")

    expected = Path("runs.jsonl").expanduser().resolve()
    assert config.metrics_path == expected
    assert isinstance(config.metrics_path, Path)
