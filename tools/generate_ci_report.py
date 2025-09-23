#!/usr/bin/env python3
"""Generate CI reliability snapshot in Markdown and JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from weekly_summary import (  # type: ignore
    aggregate_status,
    filter_by_window,
    format_percentage,
    load_flaky,
    load_runs,
    parse_iso8601,
    select_flaky_rows,
    to_float,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate CI reliability snapshot")
    parser.add_argument("--runs", type=Path, required=True, help="Path to runs.jsonl")
    parser.add_argument("--flaky", type=Path, required=True, help="Path to flaky_rank.csv")
    parser.add_argument(
        "--out-markdown",
        type=Path,
        required=True,
        help="Output path for rendered markdown",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        required=True,
        help="Output path for metrics json",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Optional path to update index markdown",
    )
    parser.add_argument("--days", type=int, default=7, help="Window size in days")
    return parser.parse_args()


def compute_last_updated(runs: List[dict]) -> Optional[str]:
    timestamps: List[dt.datetime] = []
    for run in runs:
        ts = parse_iso8601(run.get("ts"))
        if ts is not None:
            timestamps.append(ts)
    if not timestamps:
        return None
    latest = max(timestamps)
    return latest.isoformat().replace("+00:00", "Z")


def summarize_failure_kinds(runs: List[dict], limit: int = 3) -> List[dict]:
    counter: Counter[str] = Counter()
    for run in runs:
        status = (run.get("status") or "").lower()
        if status not in {"fail", "failed", "error"}:
            continue
        kind = run.get("failure_kind") or "unknown"
        counter[str(kind)] += 1
    most_common = counter.most_common(limit)
    return [
        {"kind": kind, "count": count}
        for kind, count in most_common
    ]


def normalize_flaky_rows(rows: List[dict], limit: int = 3) -> List[dict]:
    if not rows:
        return []
    sorted_rows = sorted(
        rows,
        key=lambda row: to_float(row.get("score")) or 0.0,
        reverse=True,
    )
    normalized: List[dict] = []
    for idx, row in enumerate(sorted_rows[:limit], start=1):
        attempts = row.get("attempts") or row.get("Attempts")
        normalized.append(
            {
                "rank": idx,
                "canonical_id": row.get("canonical_id") or row.get("Canonical ID") or "-",
                "attempts": int(float(attempts)) if attempts not in {None, ""} else 0,
                "p_fail": to_float(row.get("p_fail")),
                "score": to_float(row.get("score")),
                "as_of": row.get("as_of") or row.get("generated_at"),
            }
        )
    return normalized


def build_json_payload(
    *,
    generated_at: dt.datetime,
    window_days: int,
    passes: int,
    fails: int,
    errors: int,
    failure_kinds: List[dict],
    flaky_rows: List[dict],
    last_updated: Optional[str],
) -> Dict[str, Any]:
    total = passes + fails + errors
    pass_rate = (passes / total) if total else None
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "window_days": window_days,
        "totals": {
            "passes": passes,
            "fails": fails,
            "errors": errors,
            "executions": total,
        },
        "pass_rate": pass_rate,
        "failure_kinds": failure_kinds,
        "top_flaky": flaky_rows,
        "last_updated": last_updated,
    }


def format_flaky_markdown(rows: List[dict]) -> List[str]:
    header = "| Rank | Canonical ID | Attempts | p_fail | Score |"
    divider = "|-----:|--------------|---------:|------:|------:|"
    lines = [header, divider]
    if not rows:
        lines.append("| - | データなし | 0 | 0.00 | 0.00 |")
        return lines
    for row in rows:
        p_fail = row.get("p_fail")
        score = row.get("score")
        lines.append(
            "| {rank} | {cid} | {attempts} | {p_fail:.2f} | {score:.2f} |".format(
                rank=row.get("rank", "-"),
                cid=row.get("canonical_id", "-"),
                attempts=row.get("attempts", 0),
                p_fail=p_fail or 0.0,
                score=score or 0.0,
            )
        )
    return lines


def render_markdown(
    *,
    today: dt.date,
    window_days: int,
    totals: Dict[str, int],
    pass_rate: Optional[float],
    failure_kinds: List[dict],
    flaky_rows: List[dict],
    last_updated: Optional[str],
    runs_path: Path,
    flaky_path: Path,
) -> List[str]:
    kinds_summary = (
        " / ".join(f"{item['kind']} {item['count']}" for item in failure_kinds)
        if failure_kinds
        else "-"
    )
    lines: List[str] = [
        "---",
        "layout: default",
        f"title: QA Reliability Snapshot — {today.isoformat()}",
        "description: CI pass rate and flaky ranking (auto-generated)",
        "---",
        "",
        f"# QA Reliability Snapshot — {today.isoformat()}",
        "",
        f"- Window: Last {window_days} days",
        f"- Data Last Updated: {last_updated or 'N/A'}",
        "",
        "## KPI",
        "| 指標 | 値 |",
        "|------|----|",
        f"| Pass Rate | {format_percentage(pass_rate)} ({totals['passes']}/{totals['executions']}) |",
        f"| Failures | {totals['fails']} |",
        f"| Errors | {totals['errors']} |",
        f"| Top Failure Kinds | {kinds_summary} |",
        "| ソースJSON | [latest.json](./latest.json) |",
        "",
        "## Top Flaky Tests",
        *format_flaky_markdown(flaky_rows),
        "",
        "<details><summary>Generation</summary>",
        f"Source: runs={runs_path} / flaky={flaky_path}",
        f"Window: {window_days} days / Executions: {totals['executions']}",
        "Automation: tools/generate_ci_report.py (GitHub Actions)",
        "</details>",
        "",
    ]
    return lines


def update_index(index_path: Path, *, today: dt.date) -> None:
    index_lines = [
        "---",
        "layout: default",
        "title: QA Reliability Reports",
        "description: Snapshot reports generated from CI telemetry",
        "---",
        "",
        "# QA Reliability Reports",
        "",
        "最新のCI信頼性レポートとソースJSONへのリンクです。週次ワークフローで自動更新されます。",
        "",
        f"- [Latest Snapshot ({today.isoformat()})](./latest)",
        "  - [Source JSON](./latest.json)",
        "  - 更新元: tools/generate_ci_report.py",
        "",
        "過去分の保管が必要になった場合は、このフォルダに日付別のMarkdown/JSONを追加してください。",
        "",
    ]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    window = dt.timedelta(days=max(args.days, 1))
    start = now - window

    runs = load_runs(args.runs) if args.runs.exists() else []
    flaky_rows = load_flaky(args.flaky) if args.flaky.exists() else []

    filtered_runs = filter_by_window(runs, start, now)
    passes, fails, errors = aggregate_status(filtered_runs)
    failure_kinds = summarize_failure_kinds(filtered_runs)

    selected_flaky = select_flaky_rows(flaky_rows, start, now)
    normalized_flaky = normalize_flaky_rows(selected_flaky)

    last_updated = compute_last_updated(filtered_runs)

    payload = build_json_payload(
        generated_at=now,
        window_days=args.days,
        passes=passes,
        fails=fails,
        errors=errors,
        failure_kinds=failure_kinds,
        flaky_rows=normalized_flaky,
        last_updated=last_updated,
    )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    totals = payload["totals"]
    markdown_lines = render_markdown(
        today=now.date(),
        window_days=args.days,
        totals={
            "passes": totals["passes"],
            "fails": totals["fails"],
            "errors": totals["errors"],
            "executions": totals["executions"],
        },
        pass_rate=payload["pass_rate"],
        failure_kinds=failure_kinds,
        flaky_rows=normalized_flaky,
        last_updated=last_updated,
        runs_path=args.runs,
        flaky_path=args.flaky,
    )

    args.out_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.out_markdown.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    if args.index is not None:
        update_index(args.index, today=now.date())


if __name__ == "__main__":  # pragma: no cover
    main()
