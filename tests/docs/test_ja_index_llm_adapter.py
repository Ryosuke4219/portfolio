from __future__ import annotations

from pathlib import Path
import re


CLI_PROVIDER_PATTERN = re.compile(
    r"--provider(?:\s+|=)adapter/config/providers/[\w\-/]+\.ya?ml",
    re.IGNORECASE,
)
CLI_PROMPT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"--prompt(?:\s|=)",
        r"--prompt-file(?:\s|=)",
        r"--prompts(?:\s|=)",
    )
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _assert_cli_flags(snippet: str) -> None:
    normalized = _normalize_text(re.sub(r"<[^>]+>", " ", snippet))
    assert CLI_PROVIDER_PATTERN.search(
        normalized
    ), "--provider adapter/config/providers/*.yaml が不足しています"
    assert any(pattern.search(normalized) for pattern in CLI_PROMPT_PATTERNS), (
        "--prompt / --prompt-file / --prompts のいずれかが不足しています"
    )
    assert "python adapter/run_compare.py" in normalized, "Python CLI の記述がありません"


def _extract_weekly_summary_block(content: str) -> str:
    heading = "### 04. LLM Adapter — Provider Orchestration"
    start = content.find(heading)
    assert start != -1, "Weekly Summary の 04 番セクションが見つかりません"
    remainder = content[start:]
    next_heading = remainder.find("\n### ")
    return remainder if next_heading == -1 else remainder[:next_heading]


def test_llm_adapter_card_describes_provider_integration() -> None:
    content = Path("docs/index.md").read_text(encoding="utf-8")

    card_match = re.search(
        r"<article class=\"demo-card\" id=\"demo-04\">(.*?)</article>",
        content,
        re.DOTALL,
    )
    assert card_match, "04 番カードが見つかりません"

    card_block = card_match.group(1)
    _assert_cli_flags(card_block)
    normalized_card = _normalize_text(re.sub(r"<[^>]+>", " ", card_block))
    assert "data/runs-metrics.jsonl" in normalized_card, "メトリクス出力先が更新されていません"
    assert "pnpm" not in normalized_card, "旧 CLI コマンドが残っています"

    summary_block = _extract_weekly_summary_block(content)
    _assert_cli_flags(summary_block)
