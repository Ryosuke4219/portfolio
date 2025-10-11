from __future__ import annotations

from pathlib import Path

import tomllib


def test_llm_adapter_script_is_not_exposed_via_shadow_package() -> None:
    pyproject = Path("projects/04-llm-adapter-shadow/pyproject.toml")
    pyproject_data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    scripts = pyproject_data.get("project", {}).get("scripts", {})

    assert "llm-adapter" not in scripts, "Shadow package must not expose the llm-adapter script."
