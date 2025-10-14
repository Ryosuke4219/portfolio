from __future__ import annotations

from pathlib import Path
import re


def test_llm_adapter_card_describes_provider_integration() -> None:
    content = Path("docs/index.md").read_text(encoding="utf-8")
    match = re.search(
        r"<article class=\"demo-card\" id=\"demo-04\">(.*?)</article>",
        content,
        re.DOTALL,
    )
    assert match, "04 番カードが見つかりません"

    block = match.group(1)
    plain_text = re.sub(r"<[^>]+>", " ", block)
    normalized = re.sub(r"\s+", " ", plain_text).strip().casefold()

    assert "llm-adapter --provider" in normalized, "llm-adapter CLI の記述がありません"
    assert "python adapter/run_compare.py" in normalized, "Python CLI の記述がありません"
    assert "data/runs-metrics.jsonl" in normalized, "メトリクス出力先が更新されていません"
    assert "pnpm" not in normalized, "旧 CLI コマンドが残っています"
