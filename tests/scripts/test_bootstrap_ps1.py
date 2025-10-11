from __future__ import annotations

from pathlib import Path


def test_bootstrap_uses_adapter_requirements_txt() -> None:
    script_path = Path("scripts/bootstrap.ps1")
    content = script_path.read_text(encoding="utf-8")

    pip_install_lines = [
        line.strip()
        for line in content.splitlines()
        if "pip.exe" in line and "install" in line
    ]

    assert pip_install_lines, "pip install 行が検出できませんでした"

    expected_path = "projects/04-llm-adapter/requirements.txt"
    assert any(expected_path in line for line in pip_install_lines)
    assert all("projects/04-llm-adapter-shadow/requirements.txt" not in line for line in pip_install_lines)
