from __future__ import annotations

import re

from pathlib import Path


CLI_PROVIDER_PATTERN = re.compile(
    r"--provider(?:\s+|=)adapter/config/providers/[\w\-/]+\.ya?ml",
    re.IGNORECASE,
)
PROMPTS_FLAG_PATTERNS = (
    re.compile(r"--prompts(?:\s+|=)([^\s]+)", re.IGNORECASE),
    re.compile(r"--prompt-file(?:\s+|=)([^\s]+)", re.IGNORECASE),
)
PROMPTS_DATASET_PATH = Path(
    "projects/04-llm-adapter/examples/prompts/ja_one_liner.jsonl"
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _assert_cli_flags(snippet: str) -> None:
    sanitized = re.sub(r"<[^>]+>", " ", snippet)
    normalized = _normalize_text(sanitized)
    assert CLI_PROVIDER_PATTERN.search(
        normalized
    ), "--provider adapter/config/providers/*.yaml が不足しています"
    prompt_match = None
    for pattern in PROMPTS_FLAG_PATTERNS:
        prompt_match = pattern.search(sanitized)
        if prompt_match:
            break
    assert prompt_match, "--prompts または --prompt-file が不足しています"
    prompt_path = prompt_match.group(1).strip().strip("`'\"")
    assert (
        prompt_path == PROMPTS_DATASET_PATH.as_posix()
    ), "--prompts / --prompt-file は projects/04-llm-adapter/examples/prompts/ja_one_liner.jsonl を指してください"
    assert PROMPTS_DATASET_PATH.exists(), (
        f"{PROMPTS_DATASET_PATH} の実体が存在しません"
    )
    assert "--prompt " not in normalized, "旧 --prompt フラグを使用しないでください"
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
