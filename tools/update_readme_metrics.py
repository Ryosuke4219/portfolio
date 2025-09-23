#!/usr/bin/env python3
"""Update README metrics table from generated CI report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update README QA metrics table")
    parser.add_argument("--readme", type=Path, default=Path("README.md"), help="Path to README")
    parser.add_argument("--source", type=Path, required=True, help="Path to metrics JSON")
    parser.add_argument("--report-url", type=str, required=True, help="Public URL to the latest report")
    return parser.parse_args()


def load_payload(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def format_pass_rate(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_top_flaky(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "データなし"
    formatted: List[str] = []
    for row in rows[:3]:
        cid = row.get("canonical_id") or "-"
        score = row.get("score")
        if isinstance(score, (int, float)):
            formatted.append(f"{len(formatted) + 1}. {cid} (score {score:.2f})")
        else:
            formatted.append(f"{len(formatted) + 1}. {cid}")
    return "<br/>".join(formatted)


def build_table(payload: Optional[Dict[str, Any]], report_url: str) -> List[str]:
    if payload is None:
        rows = [
            "| 指標 | 値 |",
            "|------|----|",
            "| Pass Rate | N/A |",
            "| Top Flaky | データなし |",
            "| 最終更新 | N/A |",
            f"| レポート | [最新レポートを見る]({report_url}) |",
        ]
        return rows

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

    rows = [
        "| 指標 | 値 |",
        "|------|----|",
        f"| Pass Rate | {format_pass_rate(pass_rate)} ({passes}/{executions}) |",
        f"| Top Flaky | {format_top_flaky(top_flaky)} |",
        f"| 最終更新 | {last_updated} |",
        f"| レポート | [最新レポートを見る]({report_url}) |",
    ]
    return rows


def replace_section(text: str, new_lines: List[str]) -> str:
    start_marker = "<!-- qa-metrics:start -->"
    end_marker = "<!-- qa-metrics:end -->"
    if start_marker not in text or end_marker not in text:
        raise ValueError("README markers <!-- qa-metrics:start --> / <!-- qa-metrics:end --> not found")
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
