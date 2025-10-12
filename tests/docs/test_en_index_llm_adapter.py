from __future__ import annotations

import re
from pathlib import Path


def test_llm_adapter_card_describes_provider_integration() -> None:
    content = Path("docs/en/index.md").read_text(encoding="utf-8")
    match = re.search(
        r"<article class=\"demo-card\">\s*<header>\s*<p class=\"demo-card__id\">04</p>(.*?)</article>",
        content,
        re.DOTALL,
    )
    assert match, "04 番カードが見つかりません"

    block = match.group(1)
    title_match = re.search(r"<h2><a href=\"[^\"]+\">([^<]+)</a></h2>", block)
    assert title_match, "04 番カードのタイトルが取得できません"

    title = title_match.group(1)
    assert "Provider" in title, "カードタイトルに Provider が含まれていません"

    plain_text = re.sub(r"<[^>]+>", " ", block)
    normalized = re.sub(r"\s+", " ", plain_text).strip().casefold()

    assert "openai" in normalized, "OpenAI の説明がありません"
    assert "gemini" in normalized, "Gemini の説明がありません"
    assert "ollama" in normalized, "Ollama の説明がありません"
    assert "openrouter" in normalized, "OpenRouter の説明がありません"
    assert "llm-adapter --provider" in normalized, "llm-adapter CLI の記述がありません"
    assert "python adapter/run_compare.py" in normalized, "Python CLI の記述がありません"
    assert "pnpm" not in normalized, "旧 CLI コマンドが残っています"
