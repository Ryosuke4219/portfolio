from __future__ import annotations

from pathlib import Path


def test_evidence_library_includes_test_plan_label() -> None:
    index_path = Path("docs/index.md")
    content = index_path.read_text(encoding="utf-8")

    assert "- [テスト計画書]" in content
