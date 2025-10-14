from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = PROJECT_ROOT / "docs" / "index.md"


def _extract_evidence_section_lines(text: str) -> list[str]:
    lines = []
    in_section = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line == "## Evidence Library {#evidence-library}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


def test_evidence_library_contains_test_plan_label() -> None:
    content = INDEX_PATH.read_text(encoding="utf-8")
    evidence_lines = _extract_evidence_section_lines(content)
    has_test_plan_label = any(
        line.startswith("- [テスト計画書]") for line in evidence_lines
    )
    assert has_test_plan_label, (
        "Evidence Library セクションにテスト計画書リンクが存在しません。"
    )
