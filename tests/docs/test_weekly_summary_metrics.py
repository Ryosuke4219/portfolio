from __future__ import annotations

from pathlib import Path


def test_weekly_summary_exposes_kpi_placeholders() -> None:
    text = Path("docs/weekly-summary.md").read_text(encoding="utf-8")
    expected_lines = [
        "- 総テスト実行数：{{ summary.total_tests }}",
        "- テスト成功率：{{ summary.pass_rate_percent }}",
        "- 新規検出欠陥数：{{ summary.new_defects }}",
    ]

    for line in expected_lines:
        assert line in text, f"テンプレートに '{line}' が存在しません"
