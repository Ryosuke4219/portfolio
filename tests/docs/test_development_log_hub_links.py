"""docs/development-log-hub.md 内部リンク形式のガードレール。"""

from __future__ import annotations

from pathlib import Path
import re

INTERNAL_LINK_PATTERN = re.compile(
    r"\{\{\s*'/[\w\-/]+\.html'\s*\|\s*relative_url\s*\}\}"
)


SECTION_HEADINGS: tuple[str, ...] = (
    "## 注目ログ",
    "### 外部配置ログ",
)


def _collect_section_lines(lines: list[str], heading: str) -> list[str]:
    start_index = next(
        index for index, line in enumerate(lines) if line.strip() == heading
    )

    collected: list[str] = []
    heading_level = heading.count("#")

    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = stripped.count("#")
            if level <= heading_level:
                break
        collected.append(line)

    return collected


def _extract_link_targets(lines: list[str]) -> list[str]:
    targets: list[str] = []
    for line in lines:
        match = re.search(r"\[[^\]]+\]\(([^)]+)\)", line)
        if not match:
            continue
        target = match.group(1)
        if target.startswith("http://") or target.startswith("https://"):
            continue
        targets.append(target)
    return targets


def test_development_log_hub_internal_links_use_relative_url_html() -> None:
    doc_lines = Path("docs/development-log-hub.md").read_text(encoding="utf-8").splitlines()

    offenders: list[str] = []
    for heading in SECTION_HEADINGS:
        section_lines = _collect_section_lines(doc_lines, heading)
        for target in _extract_link_targets(section_lines):
            if not INTERNAL_LINK_PATTERN.fullmatch(target):
                offenders.append(f"{heading}: {target}")

    assert not offenders, (
        "docs/development-log-hub.md の内部リンクは {{ '/path.html' | relative_url }} 形式に統一してください: {targets}"
    ).format(targets=", ".join(offenders))
