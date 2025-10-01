from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_weekly_summary_generates_expected_markdown(tmp_path: Path) -> None:
    input_path = tmp_path / "runs-metrics.jsonl"
    _write_jsonl(
        input_path,
        [
            {
                "event": "shadow_diff",
                "shadow_provider": "shadow-a",
                "shadow_outcome": "success",
                "shadow_latency_ms": 1200,
            },
            {
                "event": "shadow_diff",
                "shadow_provider": "shadow-a",
                "shadow_outcome": "success",
                "shadow_latency_ms": 1400,
            },
            {
                "event": "shadow_diff",
                "shadow_provider": "shadow-a",
                "shadow_outcome": "error",
                "shadow_latency_ms": 1800,
            },
            {
                "event": "shadow_diff",
                "shadow_provider": "shadow-b",
                "shadow_outcome": "success",
                "shadow_latency_ms": 800,
            },
            {
                "event": "shadow_diff",
                "shadow_provider": "shadow-b",
                "shadow_outcome": "success",
                "shadow_latency_ms": 900,
            },
        ],
    )

    prev_path = tmp_path / "prev.md"
    prev_path.write_text(
        dedent(
            """
            # Weekly Shadow Summary

            | Provider | Failure Rate | Δ vs Prev | P95 Latency (ms) |
            | --- | --- | --- | --- |
            | shadow-a | 20.0% | n/a | 1000 |
            | shadow-b | 40.0% | n/a | 1500 |
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "weekly-summary.md"

    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.weekly_summary",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--prev",
            str(prev_path),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    expected = (
        "# Weekly Shadow Summary\n\n"
        "| Provider | Failure Rate | Δ vs Prev | P95 Latency (ms) |\n"
        "| --- | --- | --- | --- |\n"
        "| shadow-a | 33.3% | +13.3pp | 1800 |\n"
        "| shadow-b | 0.0% | -40.0pp | 900 |\n"
    )
    assert output_path.read_text(encoding="utf-8") == expected
