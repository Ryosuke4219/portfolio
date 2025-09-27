#!/usr/bin/env python3
"""Generate weekly QA summary markdown from run history and flaky ranking."""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional

__all__ = [
    "parse_iso8601",
    "load_runs",
    "load_flaky",
    "filter_by_window",
    "aggregate_status",
    "compute_failure_top",
    "extract_defect_dates",
    "count_new_defects",
    "select_flaky_rows",
    "to_float",
    "format_percentage",
    "format_table",
    "week_over_week_notes",
    "build_front_matter",
    "ensure_front_matter",
    "fallback_write",
]

ISO_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})")


def parse_iso8601(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value)
    except ValueError:
        match = ISO_RE.match(value)
        if match:
            return dt.datetime.fromisoformat(match.group("date") + "T00:00:00+00:00")
    return None


def load_runs(path: Path) -> List[dict]:
    if not path.exists():
        return []
    runs: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            runs.append(record)
    return runs


def load_flaky(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    return rows


def filter_by_window(items: Iterable[dict], start: dt.datetime, end: dt.datetime) -> List[dict]:
    results: List[dict] = []
    for item in items:
        ts = parse_iso8601(item.get("ts"))
        if ts is None:
            continue
        if start <= ts < end:
            results.append(item)
    return results


def aggregate_status(runs: Iterable[dict]) -> tuple[int, int, int]:
    passes = fails = errors = 0
    for run in runs:
        status = (run.get("status") or "").lower()
        if status == "pass":
            passes += 1
        elif status in {"fail", "failed"}:
            fails += 1
        elif status == "error":
            errors += 1
    return passes, fails, errors


def compute_failure_top(counter: Counter[str], top_n: int = 3) -> str:
    if not counter:
        return "-"
    parts: List[str] = []
    for name, count in counter.most_common(top_n):
        display = name if name else "unknown"
        parts.append(f"{display} {count}")
    return " / ".join(parts)


def extract_defect_dates(path: Path) -> List[dt.date]:
    if not path.exists():
        return []
    dates: List[dt.date] = []
    pattern = re.compile(r"-\s*起票日:\s*(\d{4}-\d{2}-\d{2})")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = pattern.search(line)
            if match:
                try:
                    dates.append(dt.date.fromisoformat(match.group(1)))
                except ValueError:
                    continue
    return dates


def count_new_defects(defect_dates: Iterable[dt.date], start: dt.date) -> int:
    return sum(1 for value in defect_dates if value >= start)


def select_flaky_rows(rows: List[dict], start: dt.datetime, end: dt.datetime) -> List[dict]:
    if not rows:
        return []
    selected: List[dict] = []
    for row in rows:
        as_of_raw = row.get("as_of") or row.get("generated_at")
        as_of_dt = parse_iso8601(as_of_raw) if as_of_raw else None
        if as_of_dt is None:
            selected.append(row)
            continue
        if start.date() <= as_of_dt.date() < end.date():
            selected.append(row)
    return selected


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def format_percentage(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_table(rows: List[dict]) -> List[str]:
    header = "| Rank | Canonical ID | Attempts | p_fail | Score |"
    divider = "|-----:|--------------|---------:|------:|------:|"
    body: List[str] = [header, divider]
    for idx, row in enumerate(rows, start=1):
        attempts = row.get("attempts") or row.get("Attempts") or "0"
        p_fail = to_float(row.get("p_fail"))
        score = to_float(row.get("score"))
        body.append(
            "| {rank} | {cid} | {attempts} | {p_fail:.2f} | {score:.2f} |".format(
                rank=idx,
                cid=row.get("canonical_id", "-"),
                attempts=int(float(attempts)) if attempts else 0,
                p_fail=p_fail or 0.0,
                score=score or 0.0,
            )
        )
    if len(body) == 2:
        body.append("| - | データなし | 0 | 0.00 | 0.00 |")
    return body


def week_over_week_notes(current_rows: List[dict], previous_rows: List[dict]) -> tuple[List[str], List[str]]:
    current_ids = [row.get("canonical_id") for row in current_rows if row.get("canonical_id")]
    previous_ids = [row.get("canonical_id") for row in previous_rows if row.get("canonical_id")]
    entered = [cid for cid in current_ids if cid not in previous_ids]
    exited = [cid for cid in previous_ids if cid not in current_ids]
    return entered, exited


def build_front_matter(today: dt.date, days: int) -> List[str]:
    return [
        "---",
        "layout: default",
        f"title: Weekly QA Summary — {today.isoformat()}",
        f"description: 直近{days}日間のQA状況サマリ",
        "---",
        "",
    ]


def ensure_front_matter(lines: List[str], today: dt.date, days: int) -> List[str]:
    stripped = list(lines)
    if stripped and stripped[0] == "---":
        try:
            closing = stripped.index("---", 1)
        except ValueError:
            stripped = stripped[1:]
        else:
            stripped = stripped[closing + 1 :]
        while stripped and stripped[0] == "":
            stripped.pop(0)
    return build_front_matter(today, days) + stripped


def fallback_write(out_path: Path, today: dt.date, days: int) -> None:
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8").splitlines()
    else:
        existing = []

    if not existing:
        placeholder = [
            f"# Weekly QA Summary — {today.isoformat()}",
            "",
            f"## Overview (last {days} days)",
            "- TotalTests: 0",
            "- PassRate: N/A",
            "- NewDefects: 0",
            "- TopFailureKinds: -",
            "",
            "## Top Flaky (score)",
            "| Rank | Canonical ID | Attempts | p_fail | Score |",
            "|-----:|--------------|---------:|------:|------:|",
            "| - | データなし | 0 | 0.00 | 0.00 |",
            "",
            "## Notes",
            "- データソースが見つからなかったため前回出力を保持しました。",
            "",
            "<details><summary>Method</summary>",
            "データソース: runs.jsonl, flaky_rank.csv / 期間: 直近7日 / 再計算: 毎週月曜 09:00 JST",
            "</details>",
            "",
        ]
        out_path.write_text(
            "\n".join(build_front_matter(today, days) + placeholder) + "\n",
            encoding="utf-8",
        )
        return

    updated = ensure_front_matter(existing, today, days)
    title_line = f"# Weekly QA Summary — {today.isoformat()}"
    for idx, line in enumerate(updated):
        if line.startswith("# Weekly QA Summary"):
            updated[idx] = title_line
            break
    else:
        updated.append(title_line)
        updated.append("")

    out_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

