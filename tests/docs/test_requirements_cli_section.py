from __future__ import annotations

from pathlib import Path
import re


def _load_cli_section() -> str:
    text = Path("docs/requirements/llm-adapter.md").read_text(encoding="utf-8")
    match = re.search(r"## 8\. コマンドライン(?P<section>.*?)(?:\n## |\Z)", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("CLIセクションが見つかりません")
    return match.group("section")


def test_cli_section_mentions_single_provider_requirements() -> None:
    section = _load_cli_section()
    assert "--provider <provider.yaml>" in section
    assert "`--out <dir>` は任意指定" in section
    assert "`metrics.jsonl` を生成・追記する" in section
    assert "Typer CLI は `run-compare` サブコマンドを提供しない" in section
