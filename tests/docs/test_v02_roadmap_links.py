from __future__ import annotations

from pathlib import Path


def test_v02_roadmap_links_llm_adapter_readme() -> None:
    roadmap_path = Path("docs/spec/v0.2/ROADMAP.md")
    roadmap_content = roadmap_path.read_text(encoding="utf-8")

    assert "projects/04-llm-adapter/README.md" in roadmap_content
