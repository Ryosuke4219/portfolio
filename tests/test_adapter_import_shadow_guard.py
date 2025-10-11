from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.mark.usefixtures("clean_adapter_modules")
def test_adapter_import_does_not_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    shadow_dir = repo_root / "projects" / "04-llm-adapter-shadow"
    target_core_dir = repo_root / "projects" / "04-llm-adapter" / "adapter" / "core"

    shadow_path = str(shadow_dir)
    cleaned_sys_path = [p for p in sys.path if p != shadow_path]
    monkeypatch.setattr(sys, "path", cleaned_sys_path)

    adapter = importlib.import_module("adapter")

    assert shadow_path not in sys.path
    core_file = Path(adapter.core.__file__).resolve()
    assert core_file.parent == target_core_dir


@pytest.fixture()
def clean_adapter_modules() -> list[str]:
    removed = [name for name in list(sys.modules) if name == "adapter" or name.startswith("adapter.")]
    for name in removed:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in removed:
            sys.modules.pop(name, None)
