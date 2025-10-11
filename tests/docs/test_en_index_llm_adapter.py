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

    assert "provider integration" in normalized, "本文で Provider 統合が説明されていません"
    assert "comparison" in normalized, "本文で比較実行が説明されていません"
    assert "cli" in normalized, "本文で CLI 情報が言及されていません"
