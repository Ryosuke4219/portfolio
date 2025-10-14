from pathlib import Path


DOC_PATH = Path("docs/weekly-summary.md")


def test_weekly_summary_metrics_placeholders() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    for placeholder in (
        "{{ summary.total_tests }}",
        "{{ summary.pass_rate_percent }}",
        "{{ summary.new_defects }}",
    ):
        assert placeholder in content, f"missing placeholder: {placeholder}"
