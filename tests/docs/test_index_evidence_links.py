"""docs/index.md の Evidence Library セクションのリンク形式を検証するテスト。"""

from __future__ import annotations

from pathlib import Path
import re

SECTION_PATTERN = re.compile(r"## Evidence Library.*?(?=\n## |\Z)", re.DOTALL)
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_evidence_library_links_use_relative_html() -> None:
    """Evidence Library のリンクが .html の relative_url 参照であることを検証。"""

    index_md = Path("docs/index.md").read_text(encoding="utf-8")
    match = SECTION_PATTERN.search(index_md)
    assert match is not None, "Evidence Library セクションが見つかりません。"

    section = match.group(0)
    links = LINK_PATTERN.findall(section)
    assert links, "Evidence Library セクションにリンクが存在しません。"

    for link in links:
        assert "relative_url" in link, f"relative_url フィルタが使われていません: {link}"
        assert ".html" in link, f".html 参照ではありません: {link}"
        assert ".md" not in link, f".md リンクが含まれています: {link}"

    assert ".md" not in section, ".md 参照が Evidence Library セクションに残っています。"
