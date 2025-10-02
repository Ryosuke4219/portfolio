from __future__ import annotations

import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

weekly_summary_cli = importlib.import_module("tools.weekly_summary.__main__")
weekly_summary = importlib.import_module("tools.weekly_summary")


def test_top_failure_kinds_includes_errored_status() -> None:
    runs = [
        {"status": "fail", "failure_kind": "unit"},
        {"status": "errored", "failure_kind": "infra"},
    ]

    counter = weekly_summary_cli._collect_failure_kinds(runs)
    top_failure = weekly_summary.compute_failure_top(counter)

    parts = [part for part in top_failure.split(" / ") if part]
    assert len(parts) == 2
