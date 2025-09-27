from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from tools.weekly_summary import (
    build_markdown,
    compute_summary,
    filter_by_window,
    write_summary,
)


@pytest.fixture
def sample_times() -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    now = dt.datetime(2024, 1, 8, 0, 0, tzinfo=dt.timezone.utc)
    window = dt.timedelta(days=7)
    current_start = now - window
    previous_start = now - window * 2
    return now, current_start, previous_start


def test_filter_by_window_filters_records(sample_times: tuple[dt.datetime, dt.datetime, dt.datetime]) -> None:
    now, current_start, _ = sample_times
    records = [
        {"ts": "2024-01-07T12:00:00+00:00"},
        {"ts": "2024-01-01T00:00:00+00:00"},
        {"ts": "2023-12-31T23:59:59+00:00"},
    ]
    filtered = filter_by_window(records, current_start, now)
    assert len(filtered) == 2
    assert all(item in filtered for item in records[:2])


def test_compute_summary_and_markdown(tmp_path: Path, sample_times: tuple[dt.datetime, dt.datetime, dt.datetime]) -> None:
    now, current_start, _ = sample_times
    today = now.date()
    days = 7

    current_runs = [
        {"status": "pass", "ts": "2024-01-07T12:00:00+00:00"},
        {"status": "fail", "failure_kind": "timeout", "ts": "2024-01-06T08:00:00+00:00"},
        {"status": "error", "failure_kind": "infra", "ts": "2024-01-05T09:00:00+00:00"},
    ]
    previous_runs = [
        {"status": "pass", "ts": "2023-12-30T12:00:00+00:00"},
        {"status": "pass", "ts": "2023-12-29T09:00:00+00:00"},
        {"status": "fail", "failure_kind": "timeout", "ts": "2023-12-28T09:00:00+00:00"},
    ]
    defect_dates = [dt.date(2024, 1, 4), dt.date(2023, 12, 20)]
    current_flaky = [
        {"canonical_id": "case.a", "score": "0.9", "p_fail": "0.5", "attempts": "5"},
        {"canonical_id": "case.b", "score": "0.4", "p_fail": "0.2", "attempts": "3"},
    ]
    previous_flaky = [
        {"canonical_id": "case.b", "score": "0.5", "p_fail": "0.3", "attempts": "4"},
    ]

    summary = compute_summary(
        today=today,
        days=days,
        current_window_start=current_start,
        current_runs=current_runs,
        previous_runs=previous_runs,
        defect_dates=defect_dates,
        current_flaky=current_flaky,
        previous_flaky=previous_flaky,
    )

    assert summary.total_tests == 3
    assert summary.top_failure == "timeout 1 / infra 1"
    assert summary.new_defects == 1
    assert summary.wow_delta is not None and summary.wow_delta < 0

    markdown_lines = build_markdown(today, days, summary)
    assert "# Weekly QA Summary" in markdown_lines[0]
    assert "- TotalTests: 3" in markdown_lines[3]
    assert any(line.startswith("- Entered:") and "case.a" in line for line in markdown_lines)

    out_path = tmp_path / "weekly.md"
    method_lines = [
        "<details><summary>Method</summary>",
        "データソース: runs.jsonl / flaky_rank.csv / 欠陥: defects.md",
        "期間: 直近7日 / 比較対象: その前の7日",
        "再計算: 毎週月曜 09:00 JST (GitHub Actions)",
        "</details>",
    ]
    write_summary(out_path, today, days, markdown_lines, method_lines=method_lines)

    contents = out_path.read_text(encoding="utf-8").splitlines()
    assert contents[0] == "---"
    assert "## Notes" in contents
    assert contents[-2] == "</details>"
