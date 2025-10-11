from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "llm_adapter.runner_async_support_shim", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(ImportError, match="adapter\\.core\\.runner_async_support"):
        spec.loader.exec_module(module)


def test_runner_async_support_shim_is_disabled() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shim_path = (
        repo_root
        / "projects"
        / "04-llm-adapter-shadow"
        / "src"
        / "llm_adapter"
        / "runner_async_support.py"
    )
    assert shim_path.exists()
    _load_module(shim_path)
