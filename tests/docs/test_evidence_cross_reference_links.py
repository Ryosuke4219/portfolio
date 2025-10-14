from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TARGET_FILES = (
    ROOT / "docs" / "evidence" / "README.md",
    ROOT / "docs" / "en" / "evidence" / "README.md",
)
EXPECTED_LINKS = {"/test-plan.html", "/defect-report-sample.html", "/weekly-summary.html"}


def extract_docs_cross_reference_section(markdown: str) -> str:
    match = re.search(r"## Docs Cross Reference(?P<section>.*?)(?:\n## |\Z)", markdown, re.S)
    if not match:
        pytest.fail("Docs Cross Reference section not found")
    return match.group("section")


def extract_relative_urls(section: str) -> set[str]:
    urls: set[str] = set()
    for line in section.splitlines():
        if line.lstrip().startswith("-"):
            urls.update(
                re.findall(r"\{\{\s*'([^']+)'\s*\|\s*relative_url\s*\}\}", line)
            )
    return urls


def test_docs_cross_reference_links_point_to_html():
    for path in TARGET_FILES:
        content = path.read_text(encoding="utf-8")
        section = extract_docs_cross_reference_section(content)
        links = extract_relative_urls(section)
        assert links == EXPECTED_LINKS, f"Unexpected links in {path}"
        assert not any(link.endswith(".md") for link in links)
        assert all(link.endswith(".html") for link in links)
