"""Shadow プロジェクトからの src.llm_adapter 直接参照を検出する防衛テスト。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Sequence

import pytest


BASE_DIR = Path(__file__).resolve().parents[2]
SHADOW_ROOT_NAME = "04-llm-adapter-shadow"

# 明示的に許可するパス（BASE_DIR からの相対パス）。
ALLOWED_PATHS: frozenset[Path] = frozenset(
    {
        # Shadow プロジェクト自身の防衛テスト。レポート対象外。
        Path(f"{SHADOW_ROOT_NAME}/tests/test_no_src_imports.py"),
    }
)

# Shadow プロジェクト内で除外するプレフィックス。
ALLOWED_PREFIXES_WITHIN_SHADOW: tuple[Path, ...] = (
    # 既存テスト群は src.llm_adapter との互換確認を目的とした参照が多数ある。
    Path("tests"),
)

# Shadow プロジェクト内で個別に除外するファイル。
ALLOWED_FILES_WITHIN_SHADOW: frozenset[Path] = frozenset(
    {
        Path("demo_shadow.py"),
    }
)


def _iter_python_files(base_dir: Path) -> Iterable[Path]:
    for path in sorted(base_dir.rglob("*.py")):
        if path.is_symlink():
            continue
        yield path


def _iter_forbidden_imports(source: str) -> Sequence[tuple[int, str]]:
    tree = ast.parse(source)
    forbidden: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                if module_name == "src.llm_adapter" or module_name.startswith("src.llm_adapter."):
                    forbidden.append((node.lineno, module_name))
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module
            if module_name and (
                module_name == "src.llm_adapter" or module_name.startswith("src.llm_adapter.")
            ):
                forbidden.append((node.lineno, module_name))

    return forbidden


@pytest.mark.skipif(not BASE_DIR.exists(), reason="ベースディレクトリが存在しない")
def test_no_direct_imports_from_src_llm_adapter() -> None:
    violations: list[str] = []

    for file_path in _iter_python_files(BASE_DIR):
        relative_path = file_path.relative_to(BASE_DIR)

        if relative_path in ALLOWED_PATHS:
            continue

        # Shadow プロジェクト配下以外はスコープ外。
        if not relative_path.parts or relative_path.parts[0] != SHADOW_ROOT_NAME:
            continue

        shadow_relative = Path(*relative_path.parts[1:])

        if shadow_relative in ALLOWED_FILES_WITHIN_SHADOW:
            continue

        if any(shadow_relative.is_relative_to(prefix) for prefix in ALLOWED_PREFIXES_WITHIN_SHADOW):
            continue

        forbidden_imports = _iter_forbidden_imports(file_path.read_text(encoding="utf-8"))
        for lineno, module_name in forbidden_imports:
            violations.append(f"{relative_path}:{lineno} -> {module_name}")

    assert not violations, "src.llm_adapter 依存を検出: \n" + "\n".join(violations)
