"""`test_runner_parallel.py` shim の削除を検知する回帰テスト。"""
from __future__ import annotations

from pathlib import Path


def test_runner_parallel_shim_removed() -> None:
    """旧シムファイルが残っていないことを保証する。"""
    repo_root = Path(__file__).resolve().parents[2]
    shim_path = repo_root / "projects" / "04-llm-adapter-shadow" / "tests" / "test_runner_parallel.py"
    assert not shim_path.exists(), (
        "projects/04-llm-adapter-shadow/tests/test_runner_parallel.py は削除済みのシムです。"
        "parallel/ 配下のテストを参照してください。"
    )
