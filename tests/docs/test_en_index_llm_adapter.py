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
PROMPTS_DATASET_PATH = "examples/prompts/ja_one_liner.jsonl"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _assert_cli_flags(snippet: str) -> None:
    normalized = _normalize_text(re.sub(r"<[^>]+>", " ", snippet))
    assert CLI_PROVIDER_PATTERN.search(
        normalized
    ), "Missing --provider adapter/config/providers/*.yaml"
    assert any(pattern.search(normalized) for pattern in CLI_PROMPT_PATTERNS), (
        "One of --prompt / --prompt-file / --prompts is required"
    )
    assert (
        PROMPTS_DATASET_PATH in normalized
    ), f"{PROMPTS_DATASET_PATH} の記述がありません"
    assert "python adapter/run_compare.py" in normalized, "Python CLI の記述がありません"


def _extract_weekly_summary_block(content: str) -> str:
    heading = "### 04. LLM Adapter — Provider Orchestration"
    start = content.find(heading)
    assert start != -1, "Weekly Summary section 04 was not found"
    remainder = content[start:]
    next_heading = remainder.find("\n### ")
    return remainder if next_heading == -1 else remainder[:next_heading]


def test_llm_adapter_card_describes_provider_integration() -> None:
    prompt_path = Path(PROMPTS_DATASET_PATH)
    if not prompt_path.exists():
        prompt_path = Path("projects/04-llm-adapter") / PROMPTS_DATASET_PATH
    assert prompt_path.exists(), f"{PROMPTS_DATASET_PATH} が存在しません"
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
