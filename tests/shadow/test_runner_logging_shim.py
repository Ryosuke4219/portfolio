"""Shadow runner logging shim が利用不可であることを検証するテスト。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.usefixtures("monkeypatch")
def test_runner_logging_shim_executes_to_error() -> None:
    """旧 shim を直接ロードすると ImportError を投げること。"""
    shim_path = (
        Path(__file__).resolve().parents[2]
        / "projects"
        / "04-llm-adapter-shadow"
        / "src"
        / "llm_adapter"
        / "runner_shared"
        / "logging.py"
    )
    assert shim_path.exists(), "shim ファイルが存在しない場合はテストを更新すること"
    spec = importlib.util.spec_from_file_location("_deprecated_logging_shim", shim_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(ModuleNotFoundError, match="adapter.core"):
        spec.loader.exec_module(module)
