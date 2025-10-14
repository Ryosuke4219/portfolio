from pathlib import Path
import re


def test_progress_report_links_use_primary_adapter() -> None:
    progress = Path("docs/04/progress-2025-10-04.md").read_text(encoding="utf-8")
    adapter_refs = re.findall(r"projects/04-llm-adapter[\w/.-]*", progress)
    assert adapter_refs, "成果物リンクが llm-adapter 本体を参照していません"
    assert "projects/04-llm-adapter-shadow" not in progress
