from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def test_runner_parallel_shim_import_raises_import_error() -> None:
    shim_path = (
        Path(__file__).resolve().parents[2]
        / "projects"
        / "04-llm-adapter-shadow"
        / "src"
        / "llm_adapter"
        / "runner_parallel.py"
    )
    spec = importlib.util.spec_from_file_location("shadow_runner_parallel_shim", shim_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with pytest.raises(ImportError) as excinfo:
        spec.loader.exec_module(module)
    message = str(excinfo.value)
    assert "shim has been removed" in message
    assert "src.llm_adapter.runner_parallel" in message
