"""開発ログハブの内部リンク形式を検証するテスト。"""

from __future__ import annotations

from pathlib import Path
import re


DOC_PATH = Path("docs/development-log-hub.md")


def _extract_section(text: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    start_index = text.find(start_marker)
    if start_index == -1:
        raise AssertionError(f"section start marker not found: {start_marker!r}")

    end_index = len(text)
    for marker in end_markers:
        marker_index = text.find(marker, start_index + len(start_marker))
        if marker_index != -1:
            end_index = min(end_index, marker_index)

    return text[start_index:end_index]


def _relative_links(section: str) -> set[str]:
    pattern = re.compile(r"\{\{\s*['\"]([^'\"]+)['\"]\s*\|\s*relative_url\s*\}\}")
    return {match.group(1) for match in pattern.finditer(section)}


def test_featured_logs_use_relative_html_links() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    section = _extract_section(text, "## 注目ログ", ("\n## ",))
    links = _relative_links(section)

    expected = {
        "/weekly-summary.html",
        "/reports/latest.html",
        "/reports/commit-summary-610-776.html",
        "/04/progress-2025-10-04.html",
    }

    assert links == expected
    assert not any(link.endswith(".md") for link in links)


def test_external_storage_logs_use_relative_html_links() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    section = _extract_section(text, "### 外部配置ログ", tuple())
    links = _relative_links(section)

    expected = {
        "/04-llm-adapter-shadow-roadmap.html",
        "/daily-review-checklist.html",
        "/04/progress-2025-10-04.html",
    }

    assert links == expected
    assert not any(link.endswith(".md") for link in links)
