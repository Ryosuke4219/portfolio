from __future__ import annotations

from pathlib import Path
import re

import pytest

DOCS = (
    Path("docs/evidence/README.md"),
    Path("docs/en/evidence/README.md"),
)


@pytest.mark.parametrize("path", DOCS)
def test_docs_cross_reference_links_use_relative_html(path: Path) -> None:
    content = path.read_text(encoding="utf-8")

    match = re.search(
        r"## Docs Cross Reference(?P<section>.*?)(?:\n## |\Z)",
        content,
        flags=re.DOTALL,
    )
    assert match is not None, f"Section 'Docs Cross Reference' not found in {path}"

    section = match.group("section")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", section)

    assert links, f"No markdown links found in 'Docs Cross Reference' section of {path}"

    for link in links:
        assert "relative_url" in link, f"{path}: link '{link}' is missing relative_url"
        assert link.startswith("{{"), f"{path}: link '{link}' should use Liquid syntax"
        assert ".html" in link, f"{path}: link '{link}' should reference an .html file"
        assert ".md" not in link, f"{path}: link '{link}' must not reference .md files"
