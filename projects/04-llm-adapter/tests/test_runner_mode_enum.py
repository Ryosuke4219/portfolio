import pytest

from adapter.core.runner_api import RunnerConfig, RunnerMode, _normalize_mode


def test_runner_mode_values_and_aliases() -> None:
    assert [mode.value for mode in RunnerMode] == [
        "sequential",
        "parallel-any",
        "parallel-all",
        "consensus",
    ]
    assert _normalize_mode("parallel") is RunnerMode.PARALLEL_ANY
    assert _normalize_mode("serial") is RunnerMode.SEQUENTIAL
    assert _normalize_mode("parallel_any") is RunnerMode.PARALLEL_ANY
    assert _normalize_mode("parallel-all") is RunnerMode.PARALLEL_ALL


def test_runner_config_keeps_enum() -> None:
    config = RunnerConfig(mode=RunnerMode.CONSENSUS)
    assert isinstance(config.mode, RunnerMode)
    assert config.mode is RunnerMode.CONSENSUS


@pytest.mark.parametrize(
    "value, expected",
    [
        (RunnerMode.SEQUENTIAL, RunnerMode.SEQUENTIAL),
        ("sequential", RunnerMode.SEQUENTIAL),
        ("parallel-any", RunnerMode.PARALLEL_ANY),
        ("parallel_all", RunnerMode.PARALLEL_ALL),
        ("consensus", RunnerMode.CONSENSUS),
    ],
)
def test_normalize_mode_accepts_enum_and_strings(value, expected) -> None:
    assert _normalize_mode(value) is expected
