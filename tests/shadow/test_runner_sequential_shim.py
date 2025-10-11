from __future__ import annotations

from importlib.machinery import PathFinder
from pathlib import Path


def test_runner_sequential_shim_is_absent() -> None:
    shim_dir = (
        Path(__file__)
        .resolve()
        .parents[2]
        / "projects"
        / "04-llm-adapter-shadow"
        / "tests"
    )
    spec = PathFinder.find_spec("test_runner_sequential", [str(shim_dir)])
    assert spec is None, "Legacy sequential runner shim should be removed"
