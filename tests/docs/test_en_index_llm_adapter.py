from __future__ import annotations

from pathlib import Path
import re

CLI_PROVIDER_PATTERN = re.compile(
    r"--provider(?:\s+|=)adapter/config/providers/[\w\-/]+\.ya?ml",
    re.IGNORECASE,
)
RUN_COMPARE_PROVIDERS_ARG = "--providers adapter/config/providers/openai.yaml"
PROMPTS_FLAG_PATTERNS = (
    re.compile(r"--prompts(?:\s+|=)([^\s]+)", re.IGNORECASE),
    re.compile(r"--prompt-file(?:\s+|=)([^\s]+)", re.IGNORECASE),
)
PROMPTS_DATASET_PATH = Path(
    "projects/04-llm-adapter/examples/prompts/ja_one_liner.jsonl"
)
PROMPTS_PATH = Path("examples/prompts/ja_one_liner.jsonl")
expected_prompts_arg = f"--prompts {PROMPTS_PATH.as_posix()}"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _assert_cli_flags(snippet: str) -> None:
    sanitized = re.sub(r"<[^>]+>", " ", snippet)
    normalized = _normalize_text(sanitized)
    assert CLI_PROVIDER_PATTERN.search(
        normalized
    ), "Missing --provider adapter/config/providers/*.yaml"
    assert (
        RUN_COMPARE_PROVIDERS_ARG in normalized
    ), f"Missing {RUN_COMPARE_PROVIDERS_ARG}"
    prompt_match = None
    for pattern in PROMPTS_FLAG_PATTERNS:
        prompt_match = pattern.search(sanitized)
        if prompt_match:
            break
    assert prompt_match, "Either --prompts or --prompt-file must be provided"
    assert (
        expected_prompts_arg in normalized
    ), f"CLI は {PROMPTS_PATH} を参照してください"
    assert "adapter/prompts/demo-04.yaml" not in normalized, "adapter/prompts/demo-04.yaml は存在しません"
    assert "adapter/prompts/" not in normalized, "adapter/prompts/ ディレクトリは存在しません"
    assert PROMPTS_PATH.exists(), f"{PROMPTS_PATH} が存在しません"
    assert "python adapter/run_compare.py" in normalized, "Python CLI の記述がありません"


def _extract_weekly_summary_block(content: str) -> str:
    heading = "### 04. LLM Adapter — Provider Orchestration"
    start = content.find(heading)
    assert start != -1, "Weekly Summary section 04 was not found"
    remainder = content[start:]
    next_heading = remainder.find("\n### ")
    return remainder if next_heading == -1 else remainder[:next_heading]


def test_llm_adapter_card_describes_provider_integration() -> None:
    assert PROMPTS_DATASET_PATH.exists(), (
        f"{PROMPTS_DATASET_PATH} が存在しません"
    )
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
