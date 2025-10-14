from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TARGET_DOCS: tuple[Path, ...] = (
    PROJECT_ROOT / "docs" / "evidence" / "README.md",
    PROJECT_ROOT / "docs" / "en" / "evidence" / "README.md",
)

EXPECTED_HTML_LINKS: tuple[str, ...] = (
    "{{ '/test-plan.html' | relative_url }}",
    "{{ '/defect-report-sample.html' | relative_url }}",
    "{{ '/weekly-summary.html' | relative_url }}",
)

SECTION_PATTERN = re.compile(
    r"## Docs Cross Reference(?P<section>.*?)(?:\n## |\Z)",
    flags=re.DOTALL,
)


def _extract_links(section: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", section)


def _assert_links_are_html_only(path: Path, links: Iterable[str]) -> None:
    missing_targets = [target for target in EXPECTED_HTML_LINKS if target not in links]
    assert not missing_targets, (
        f"{path}: missing expected HTML targets: {missing_targets}"
    )

    invalid_targets = [link for link in links if ".md" in link or ".html" not in link]
    assert not invalid_targets, (
        f"{path}: found non-HTML cross references: {invalid_targets}"
    )


@pytest.mark.parametrize("path", TARGET_DOCS)
def test_docs_cross_reference_links_use_relative_html(path: Path) -> None:
    content = path.read_text(encoding="utf-8")

    match = SECTION_PATTERN.search(content)
    assert match is not None, f"Section 'Docs Cross Reference' not found in {path}"

    links = _extract_links(match.group("section"))
    assert links, f"No markdown links found in 'Docs Cross Reference' section of {path}"

    _assert_links_are_html_only(path, links)
