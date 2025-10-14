from __future__ import annotations

from pathlib import Path
import re


CLI_PROVIDER_PATTERN = re.compile(
    r"llm-adapter[^\n`]*--provider\s+adapter/config/providers/[\w-]+\.ya?ml",
    re.IGNORECASE,
)
CLI_PROMPT_PATTERN = re.compile(r"--prompt(?:-file|s)?(?:\s|=)", re.IGNORECASE)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _assert_cli_flags(snippet: str) -> None:
    normalized = _normalize_text(re.sub(r"<[^>]+>", " ", snippet))
    assert CLI_PROVIDER_PATTERN.search(
        normalized
    ), "provider 設定ファイルへのパスが記載されていません"
    assert CLI_PROMPT_PATTERN.search(normalized), "プロンプト指定フラグが不足しています"
    assert "python adapter/run_compare.py" in normalized, "Python CLI の記述がありません"


def _extract_weekly_summary_block(content: str) -> str:
    heading = "### 04. LLM Adapter — Provider Orchestration"
    start = content.find(heading)
    assert start != -1, "Weekly Summary section 04 was not found"
    remainder = content[start:]
    next_heading = remainder.find("\n### ")
    return remainder if next_heading == -1 else remainder[:next_heading]


def test_llm_adapter_card_describes_provider_integration() -> None:
    content = Path("docs/en/index.md").read_text(encoding="utf-8")

    card_match = re.search(
        r"<article class=\"demo-card\">\s*<header>\s*<p class=\"demo-card__id\">04</p>(.*?)</article>",
        content,
        re.DOTALL,
    )
    assert card_match, "04 番カードが見つかりません"

    card_block = card_match.group(1)
    title_match = re.search(r"<h2><a href=\"[^\"]+\">([^<]+)</a></h2>", card_block)
    assert title_match, "04 番カードのタイトルが取得できません"
    title = title_match.group(1)
    assert "Provider" in title, "カードタイトルに Provider が含まれていません"

    normalized_card = _normalize_text(re.sub(r"<[^>]+>", " ", card_block))
    for keyword in ("openai", "gemini", "ollama", "openrouter"):
        assert keyword in normalized_card, f"{keyword} の説明がありません"

    _assert_cli_flags(card_block)
    assert "pnpm" not in normalized_card, "旧 CLI コマンドが残っています"

    summary_block = _extract_weekly_summary_block(content)
    _assert_cli_flags(summary_block)
