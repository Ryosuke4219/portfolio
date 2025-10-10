from __future__ import annotations

from pathlib import Path
import tomllib


def test_pyproject_contains_required_dependencies() -> None:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        pyproject_data = tomllib.load(pyproject_file)

    dependencies = pyproject_data["project"]["dependencies"]

    assert "PyYAML>=6.0" in dependencies
    assert "requests>=2.31.0" in dependencies
    assert "google-genai>=0.3" in dependencies
