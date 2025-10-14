from __future__ import annotations

from pathlib import Path


def test_weekly_summary_exposes_kpi_placeholders() -> None:
    text = Path("docs/weekly-summary.md").read_text(encoding="utf-8")
    expected_tokens = [
        "{{ summary.total_tests }}",
        "{{ summary.pass_rate_percent }}",
        "{{ summary.new_defects }}",
    ]

    for token in expected_tokens:
        assert token in text, f"テンプレートに {token} が存在しません"
