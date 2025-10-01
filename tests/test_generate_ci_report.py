import datetime as dt
from pathlib import Path

import pytest

from tools.ci_report.processing import compute_last_updated, normalize_flaky_rows
from tools.ci_report.rendering import render_markdown
from tools.weekly_summary import select_flaky_rows


@pytest.fixture
def sample_runs() -> list[dict[str, object]]:
    return [
        {"ts": "2024-06-01T12:00:00Z", "status": "pass"},
        {"ts": "2024-06-02T09:00:00Z", "status": "fail"},
        {"ts": None, "status": "error"},
    ]


def test_compute_last_updated(sample_runs: list[dict[str, object]]) -> None:
    assert compute_last_updated(sample_runs) == "2024-06-02T09:00:00Z"


def test_normalize_flaky_rows_sorts_and_limits() -> None:
    rows = [
        {"canonical_id": "a", "score": "0.2", "p_fail": "0.1", "attempts": "2"},
        {"canonical_id": "b", "score": "0.5", "p_fail": "0.3", "attempts": 3},
        {"canonical_id": "c", "score": "0.1", "p_fail": "0.4", "attempts": True},
    ]

    normalized = normalize_flaky_rows(rows, limit=2)

    assert [row["canonical_id"] for row in normalized] == ["b", "a"]
    assert normalized[0]["rank"] == 1
    assert normalized[1]["attempts"] == 2


def test_render_markdown_includes_summary(sample_runs: list[dict[str, object]]) -> None:
    markdown = render_markdown(
        today=dt.date(2024, 6, 5),
        window_days=7,
        totals={"passes": 1, "fails": 1, "errors": 1, "executions": 3},
        pass_rate=1 / 3,
        failure_kinds=[{"kind": "flake", "count": 2}],
        flaky_rows=[{"rank": 1, "canonical_id": "a", "attempts": 2, "p_fail": 0.3, "score": 0.6}],
        last_updated="2024-06-02T09:00:00Z",
        runs_path=Path("runs.jsonl"),
        flaky_path=Path("flaky.csv"),
    )

    assert any("# QA Reliability Snapshot — 2024-06-05" in line for line in markdown)
    assert any("flake 2" in line for line in markdown)


def test_render_markdown_formats_numeric_strings() -> None:
    markdown = render_markdown(
        today=dt.date(2024, 6, 5),
        window_days=7,
        totals={"passes": 1, "fails": 0, "errors": 0, "executions": 1},
        pass_rate=1.0,
        failure_kinds=[],
        flaky_rows=[
            {
                "rank": 1,
                "canonical_id": "sample",
                "attempts": "3",
                "p_fail": "0.25",
                "score": "0.5",
            }
        ],
        last_updated="2024-06-05T09:00:00Z",
        runs_path=Path("runs.jsonl"),
        flaky_path=Path("flaky.csv"),
    )

    table_line = next(line for line in markdown if line.startswith("| 1 |"))
    assert table_line.endswith("| 3 | 0.25 | 0.50 |")


def test_select_flaky_rows_includes_end_date() -> None:
    start = dt.datetime(2024, 6, 2, tzinfo=dt.timezone.utc)
    end = dt.datetime(2024, 6, 9, tzinfo=dt.timezone.utc)
    rows = [
        {"canonical_id": "kept", "as_of": "2024-06-09T10:00:00Z"},
        {"canonical_id": "excluded", "as_of": "2024-06-10T00:00:00Z"},
    ]

    selected = select_flaky_rows(rows, start=start, end=end)

    assert [row["canonical_id"] for row in selected] == ["kept"]
