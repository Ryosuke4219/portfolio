from __future__ import annotations

import datetime as dt
import importlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

weekly_summary = importlib.import_module("tools.weekly_summary")
legacy_load_runs = weekly_summary.load_runs
legacy_load_flaky = weekly_summary.load_flaky

@pytest.mark.parametrize(
    "loader, filename, payload, expected",
    [
        (legacy_load_runs, "runs.jsonl", "{\"status\": \"pass\"}\n", [{"status": "pass"}]),
        (
            legacy_load_flaky,
            "flaky.csv",
            "canonical_id,score\na,0.1\n",
            [{"canonical_id": "a", "score": "0.1"}],
        ),
    ],
)
def test_legacy_exports_continue_to_work(
    tmp_path: Path, loader, filename: str, payload: str, expected: list[dict[str, object]]
) -> None:
    target = tmp_path / filename
    target.write_text(payload, encoding="utf-8")
    assert loader(target) == expected


def test_io_module_provides_same_interfaces(tmp_path: Path) -> None:
    io_module = importlib.import_module("tools.weekly_summary.io")
    load_runs = io_module.load_runs
    load_flaky = io_module.load_flaky
    filter_by_window = io_module.filter_by_window

    runs_path = tmp_path / "runs.jsonl"
    runs_path.write_text(
        "\n".join(
            [
                "{\"status\": \"pass\", \"ts\": \"2024-01-01T00:00:00+00:00\"}",
                "{\"status\": \"fail\", \"ts\": \"2025-01-01T00:00:00+00:00\"}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    flaky_path = tmp_path / "flaky.csv"
    flaky_path.write_text("canonical_id,score\na,0.1\n", encoding="utf-8")

    runs = load_runs(runs_path)
    flaky = load_flaky(flaky_path)
    window = filter_by_window(
        runs,
        dt.datetime(2023, 1, 1, tzinfo=dt.UTC),
        dt.datetime(2024, 6, 1, tzinfo=dt.UTC),
    )

    assert runs[0]["status"] == "pass"
    assert flaky == [{"canonical_id": "a", "score": "0.1"}]
    assert window == [runs[0]]
