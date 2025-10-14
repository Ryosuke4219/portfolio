from __future__ import annotations

from pathlib import Path


EXPECTED_LINK_LINES = {
    "- [QA Evidence Catalog]({{ '/evidence/README.html' | relative_url }})",
    "- [テスト計画書]({{ '/test-plan.html' | relative_url }})",
    "- [欠陥レポートサンプル]({{ '/defect-report-sample.html' | relative_url }})",
}


def test_japanese_index_evidence_links_use_relative_url_html() -> None:
    index_path = Path("docs/index.md")
    content = index_path.read_text(encoding="utf-8")

    section_start = content.index("## Evidence Library")
    section = content[section_start:]
    lines = section.splitlines()[1:]

    evidence_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            evidence_lines.append(line.strip())

    assert evidence_lines, "Evidence Library section should contain bullet links"
    assert set(evidence_lines) == EXPECTED_LINK_LINES
    assert not any(".md" in line for line in evidence_lines)
    assert all("relative_url" in line for line in evidence_lines)
