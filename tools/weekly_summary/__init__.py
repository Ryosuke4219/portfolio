#!/usr/bin/env python3
"""Generate weekly QA summary markdown from run history and flaky ranking."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import datetime as dt
from pathlib import Path
import re

from .io import filter_by_window, load_flaky, load_runs, parse_iso8601

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
    "coerce_str",
    "to_float",
    "format_percentage",
    "format_table",
    "week_over_week_notes",
    "build_front_matter",
    "ensure_front_matter",
    "fallback_write",
]


def aggregate_status(runs: Iterable[dict[str, object]]) -> tuple[int, int, int]:
    from tools.ci_metrics import normalize_status  # local import to avoid cycle

    passes = fails = errors = 0
    for run in runs:
        status_raw = coerce_str(run.get("status"))
        if status_raw is None:
            continue
        status = normalize_status(status_raw)
        if status == "pass":
            passes += 1
        elif status == "fail":
            fails += 1
        elif status == "error":
            errors += 1
    return passes, fails, errors


def compute_failure_top(counter: Counter[str], top_n: int = 3) -> str:
    if not counter:
        return "-"
    parts: list[str] = []
    for name, count in counter.most_common(top_n):
        display = name if name else "unknown"
        parts.append(f"{display} {count}")
    return " / ".join(parts)


def extract_defect_dates(path: Path) -> list[dt.date]:
    if not path.exists():
        return []
    dates: list[dt.date] = []
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


def select_flaky_rows(
    rows: list[dict[str, object]], start: dt.datetime, end: dt.datetime
) -> list[dict[str, object]]:
    if not rows:
        return []
    selected: list[dict[str, object]] = []
    for row in rows:
        as_of_raw = coerce_str(row.get("as_of")) or coerce_str(row.get("generated_at"))
        as_of_dt = parse_iso8601(as_of_raw) if as_of_raw else None
        if as_of_dt is None:
            selected.append(row)
            continue
        if start.date() <= as_of_dt.date() <= end.date():
            selected.append(row)
    return selected


def coerce_str(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (bool, int, float)):  # noqa: UP038
        return str(value)
    return None

def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):  # noqa: UP038
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def format_percentage(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_table(rows: list[dict[str, object]]) -> list[str]:
    header = "| Rank | Canonical ID | Attempts | p_fail | Score |"
    divider = "|-----:|--------------|---------:|------:|------:|"
    body: list[str] = [header, divider]
    for idx, row in enumerate(rows, start=1):
        attempts_value = to_float(row.get("attempts"))
        if attempts_value is None:
            attempts_value = to_float(row.get("Attempts"))
        p_fail_value = to_float(row.get("p_fail"))
        score_value = to_float(row.get("score"))
        body.append(
            "| {rank} | {cid} | {attempts} | {p_fail:.2f} | {score:.2f} |".format(
                rank=idx,
                cid=coerce_str(row.get("canonical_id")) or "-",
                attempts=int(attempts_value) if attempts_value is not None else 0,
                p_fail=p_fail_value or 0.0,
                score=score_value or 0.0,
            )
        )
    if len(body) == 2:
        body.append("| - | データなし | 0 | 0.00 | 0.00 |")
    return body


def week_over_week_notes(
    current_rows: list[dict[str, object]], previous_rows: list[dict[str, object]]
) -> tuple[list[str], list[str]]:
    current_ids = [
        canonical_id
        for row in current_rows
        for canonical_id in [coerce_str(row.get("canonical_id"))]
        if canonical_id
    ]
    previous_ids = [
        canonical_id
        for row in previous_rows
        for canonical_id in [coerce_str(row.get("canonical_id"))]
        if canonical_id
    ]
    entered = [cid for cid in current_ids if cid not in previous_ids]
    exited = [cid for cid in previous_ids if cid not in current_ids]
    return entered, exited


def build_front_matter(today: dt.date, days: int) -> list[str]:
    return [
        "---",
        "layout: default",
        f"title: Weekly QA Summary — {today.isoformat()}",
        f"description: 直近{days}日間のQA状況サマリ",
        "---",
        "",
    ]


def ensure_front_matter(lines: list[str], today: dt.date, days: int) -> list[str]:
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
