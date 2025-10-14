"""Guardrails for Development Log Hub link formats."""

from __future__ import annotations

from pathlib import Path

TARGET_LINKS: dict[str, str] = {
    "週次サマリ": "/weekly-summary.html",
    "最新の CI 信頼性レポート": "/reports/latest.html",
    "コミットサマリ 610-776": "/reports/commit-summary-610-776.html",
    "Shadow Roadmap": "/04-llm-adapter-shadow-roadmap.html",
    "Daily Review Checklist": "/daily-review-checklist.html",
}


SECTION_HEADINGS: tuple[str, ...] = ("## 注目ログ", "### 外部配置ログ")


def _iter_section_bullet_lines(lines: list[str], heading: str) -> list[str]:
    """Return bullet lines that belong to a given heading."""

    try:
        start_index = lines.index(heading)
    except ValueError as error:  # pragma: no cover - guard via assertion in caller.
        raise AssertionError(f"{heading} が docs/development-log-hub.md に見つかりません。") from error

    bullet_lines: list[str] = []
    for line in lines[start_index + 1 :]:
        if heading.startswith("### ") and line.startswith("## "):
            break
        if heading.startswith("## ") and line.startswith("## ") and line != heading:
            break
        if heading.startswith("### ") and line.startswith("### ") and line != heading:
            break
        if line.startswith("- "):
            bullet_lines.append(line)
    return bullet_lines


def test_development_log_hub_highlight_links_use_relative_url() -> None:
    content = Path("docs/development-log-hub.md").read_text(encoding="utf-8")
    lines = content.splitlines()

    for heading in SECTION_HEADINGS:
        section_bullets = _iter_section_bullet_lines(lines, heading)
        assert section_bullets, f"{heading} セクションに箇条書きリンクが見つかりません。"
        for bullet in section_bullets:
            if "://" in bullet:
                continue
            assert ".md" not in bullet, f"{heading} の箇条書きリンクを .html 形式に揃えてください: {bullet}"

    for label, href in TARGET_LINKS.items():
        expected = f"[{label}]({{{{ '{href}' | relative_url }}}})"
        assert expected in content, (
            "docs/development-log-hub.md の {label} リンクは {{ '/path.html' | relative_url }} 形式に統一してください。"
        )
