from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from .data import count_new_defects


@dataclass
class SummaryData:
    total_tests: int
    pass_rate: Optional[float]
    new_defects: int
    top_failure: str
    table_lines: List[str]
    wow_delta: Optional[float]
    entered: List[str]
    exited: List[str]
    notes: List[str]


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


def format_table(rows: Sequence[dict]) -> List[str]:
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


def week_over_week_notes(current_rows: Sequence[dict], previous_rows: Sequence[dict]) -> tuple[List[str], List[str]]:
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


def compute_summary(
    *,
    today: dt.date,
    days: int,
    current_window_start: dt.datetime,
    current_runs: Sequence[dict],
    previous_runs: Sequence[dict],
    defect_dates: Iterable[dt.date],
    current_flaky: Sequence[dict],
    previous_flaky: Sequence[dict],
) -> SummaryData:
    passes, fails, errors = aggregate_status(current_runs)
    prev_passes, prev_fails, prev_errors = aggregate_status(previous_runs)

    total_tests = passes + fails + errors
    prev_total = prev_passes + prev_fails + prev_errors

    pass_rate = (passes / total_tests) if total_tests else None
    prev_pass_rate = (prev_passes / prev_total) if prev_total else None

    failure_counter: Counter[str] = Counter()
    for run in current_runs:
        status = (run.get("status") or "").lower()
        if status not in {"fail", "failed", "error"}:
            continue
        kind = run.get("failure_kind") or "unknown"
        failure_counter[kind] += 1

    top_failure = compute_failure_top(failure_counter)

    new_defects = count_new_defects(defect_dates, current_window_start.date())

    def sort_flaky(rows: Sequence[dict]) -> List[dict]:
        return sorted(rows, key=lambda row: to_float(row.get("score")) or 0.0, reverse=True)

    current_flaky_sorted = sort_flaky(current_flaky)[:5]
    previous_flaky_sorted = sort_flaky(previous_flaky)[:5]

    table_lines = format_table(current_flaky_sorted)
    entered, exited = week_over_week_notes(current_flaky_sorted, previous_flaky_sorted)

    wow_delta = None
    if pass_rate is not None and prev_pass_rate is not None:
        wow_delta = (pass_rate - prev_pass_rate) * 100

    notes: List[str] = []
    if wow_delta is not None:
        notes.append(f"PassRate WoW: {wow_delta:+.2f}pp (prev {prev_pass_rate * 100:.2f}%).")
    elif pass_rate is not None:
        notes.append(f"PassRate: {pass_rate * 100:.2f}% (過去週データ不足)")
    else:
        notes.append("PassRate算出対象となるテストがありません。")

    if entered:
        notes.append("Top Flaky 新規: " + ", ".join(entered))
    if exited:
        notes.append("Top Flaky 離脱: " + ", ".join(exited))
    if not notes:
        notes.append("特記事項なし。")

    return SummaryData(
        total_tests=total_tests,
        pass_rate=pass_rate,
        new_defects=new_defects,
        top_failure=top_failure,
        table_lines=table_lines,
        wow_delta=wow_delta,
        entered=entered,
        exited=exited,
        notes=notes,
    )


def build_markdown(today: dt.date, days: int, summary: SummaryData) -> List[str]:
    markdown_lines: List[str] = [
        f"# Weekly QA Summary — {today.isoformat()}",
        "",
        f"## Overview (last {days} days)",
        f"- TotalTests: {summary.total_tests}",
        f"- PassRate: {format_percentage(summary.pass_rate)}",
        f"- NewDefects: {summary.new_defects}",
        f"- TopFailureKinds: {summary.top_failure}",
        "",
        "## Top Flaky (score)",
        *summary.table_lines,
        "",
        "## Week-over-Week",
        (
            f"- PassRate Δ: {summary.wow_delta:+.2f}pp"
            if summary.wow_delta is not None
            else "- PassRate Δ: N/A"
        ),
        f"- Entered: {', '.join(summary.entered) if summary.entered else 'なし'}",
        f"- Exited: {', '.join(summary.exited) if summary.exited else 'なし'}",
        "",
        "## Notes",
        *[f"- {note}" for note in summary.notes],
    ]
    return markdown_lines
