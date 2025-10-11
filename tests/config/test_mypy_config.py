from __future__ import annotations

from pathlib import Path
import re
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def load_mypy_config() -> dict:
    with PYPROJECT_PATH.open("rb") as file:
        pyproject = tomllib.load(file)
    return pyproject["tool"]["mypy"]


def test_mypy_path_points_to_primary_project() -> None:
    config = load_mypy_config()
    mypy_path = config["mypy_path"]

    assert "projects/04-llm-adapter" in mypy_path
    assert "projects/04-llm-adapter-shadow" not in mypy_path


def test_exclude_does_not_drop_core_package() -> None:
    config = load_mypy_config()
    pattern = re.compile(config["exclude"]) if config.get("exclude") else None

    assert pattern is not None, "exclude pattern should be defined to keep tests precise"

    core_init = "projects/04-llm-adapter/adapter/core/__init__.py"
    assert not pattern.match(core_init), "core package should not be entirely excluded"
