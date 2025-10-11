from __future__ import annotations

from pathlib import Path


def test_release_v02_links_point_to_core_adapter() -> None:
    release_note = Path("docs/releases/v0.2.md")
    content = release_note.read_text(encoding="utf-8")

    assert "projects/04-llm-adapter/" in content, "LLM Adapter core へのリンクが不足しています"
    assert (
        "projects/04-llm-adapter-shadow" not in content
    ), "旧 shadow パスへのリンクを含めないでください"
