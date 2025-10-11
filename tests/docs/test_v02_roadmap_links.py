"""docs/spec/v0.2/ROADMAP.md のリンク検証テスト."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


def test_openrouter_setup_link_points_to_existing_readme_section() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    roadmap_path = repo_root / "docs/spec/v0.2/ROADMAP.md"
    roadmap_text = roadmap_path.read_text(encoding="utf-8")

    match = re.search(r"\[サンプル設定とプロンプト\]\(([^)]+)\)", roadmap_text)
    assert match is not None, "ターゲットリンクが ROADMAP.md から見つかりません。"

    link = match.group(1)
    parsed = urlparse(link)
    assert parsed.scheme in {"http", "https"}, "相対リンクのままでは GitHub Pages で 404 になります。"
    assert parsed.netloc.endswith("github.com"), "GitHub README 以外へのリンクになっています。"
    assert parsed.path.endswith("/projects/04-llm-adapter/README.md"), "LLM Adapter README へのリンクではありません。"

    anchor = unquote(parsed.fragment)
    readme_path = repo_root / "projects/04-llm-adapter/README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    heading_pattern = re.compile(rf"^##\s+{re.escape(anchor)}\s*$", re.MULTILINE)
    assert heading_pattern.search(readme_text) is not None, f"README.md に '#{anchor}' セクションが存在しません。"
