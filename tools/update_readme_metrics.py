#!/usr/bin/env python3
"""Update README metrics table from generated CI report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

README_MARKERS_NOT_FOUND = (
    "README markers <!-- qa-metrics:start --> / <!-- qa-metrics:end --> not found"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update README QA metrics table")
    parser.add_argument("--readme", type=Path, default=Path("README.md"), help="Path to README")
    parser.add_argument("--source", type=Path, required=True, help="Path to metrics JSON")
    parser.add_argument(
        "--report-url",
        type=str,
        required=True,
        help="Public URL to the latest report",
    )
    return parser.parse_args()


def load_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def format_pass_rate(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_top_flaky(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "データなし"
    formatted: list[str] = []
    for row in rows[:3]:
        cid = row.get("canonical_id") or "-"
        score = row.get("score")
        if isinstance(score, int | float):
            formatted.append(f"{len(formatted) + 1}. {cid} (score {score:.2f})")
        else:
            formatted.append(f"{len(formatted) + 1}. {cid}")
    return "<br/>".join(formatted)


def format_pass_rate_delta(value: float | None) -> str:
    if value is None:
        return " (基準なし)"
    if abs(value) < 1e-9:
        return " (±0.00pp)"
    sign = "+" if value > 0 else "-"
    return f" ({sign}{abs(value) * 100:.2f}pp)"


def format_int_delta(value: int | None) -> str:
    if value is None:
        return " (基準なし)"
    if value == 0:
        return " (±0)"
    sign = "+" if value > 0 else "-"
    return f" ({sign}{abs(value)})"


def format_recent_runs(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return []
    lines = ["直近3回の差分:"]
    for item in reversed(items):  # 最新順
        run_id = item.get("run_id") or "-"
        ts = item.get("ts") or "N/A"
        pass_rate = format_pass_rate(item.get("pass_rate"))
        pass_delta = format_pass_rate_delta(item.get("pass_rate_delta"))
        flaky_count = item.get("flaky_count") or 0
        flaky_delta = format_int_delta(item.get("flaky_delta"))
        lines.append(
            f"- {run_id} ({ts}): Pass Rate {pass_rate}{pass_delta} / "
            f"Flaky {flaky_count}件{flaky_delta}"
        )
    return lines


def build_table(payload: dict[str, Any] | None, report_url: str) -> list[str]:
    if payload is None:
        table = [
            "| 指標 | 値 |",
            "|------|----|",
            "| Pass Rate | N/A |",
            "| Top Flaky | データなし |",
            "| 最終更新 | N/A |",
            f"| レポート | [最新レポートを見る]({report_url}) |",
        ]
        return table

    totals = payload.get("totals", {})
    executions = totals.get("executions") or 0
    passes = totals.get("passes") or 0
    pass_rate = payload.get("pass_rate")
    top_flaky = payload.get("top_flaky") or []
    last_updated = payload.get("last_updated") or "N/A"
    if isinstance(last_updated, str):
        # Normalize to ISO8601 without microseconds when possible
        try:
            parsed = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            last_updated = parsed.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass

    table = [
        "| 指標 | 値 |",
        "|------|----|",
        f"| Pass Rate | {format_pass_rate(pass_rate)} ({passes}/{executions}) |",
        f"| Top Flaky | {format_top_flaky(top_flaky)} |",
        f"| 最終更新 | {last_updated} |",
        f"| レポート | [最新レポートを見る]({report_url}) |",
    ]
    recent_lines = format_recent_runs(payload.get("recent_runs") or [])
    if recent_lines:
        table.append("")
        table.extend(recent_lines)
    return table


def replace_section(text: str, new_lines: list[str]) -> str:
    start_marker = "<!-- qa-metrics:start -->"
    end_marker = "<!-- qa-metrics:end -->"
    if start_marker not in text or end_marker not in text:
        raise ValueError(README_MARKERS_NOT_FOUND)
    start_index = text.index(start_marker) + len(start_marker)
    end_index = text.index(end_marker)
    before = text[:start_index]
    after = text[end_index:]
    body = "\n" + "\n".join(new_lines) + "\n"
    if not after.startswith("\n"):
        after = "\n" + after
    return before + body + after


def main() -> None:
    args = parse_args()
    payload = load_payload(args.source)
    table_lines = build_table(payload, args.report_url)
    original = args.readme.read_text(encoding="utf-8")
    updated = replace_section(original, table_lines)
    args.readme.write_text(updated, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
