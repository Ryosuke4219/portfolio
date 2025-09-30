#!/usr/bin/env python3
"""Generate CI reliability snapshot in Markdown and JSON."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ci_metrics import compute_recent_deltas, compute_run_history
from weekly_summary import (
    aggregate_status,
    coerce_str,
    filter_by_window,
    format_percentage,
    load_flaky,
    load_runs,
    parse_iso8601,
    select_flaky_rows,
    to_float,
)

from tools.ci_report.processing import (
    compute_last_updated,
    normalize_flaky_rows,
    summarize_failure_kinds,
)
from tools.ci_report.rendering import build_json_payload, render_markdown


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


def compute_last_updated(runs: list[dict[str, object]]) -> str | None:
    timestamps: list[dt.datetime] = []
    for run in runs:
        ts = parse_iso8601(coerce_str(run.get("ts")))
        if ts is not None:
            timestamps.append(ts)
    if not timestamps:
        return None
    latest = max(timestamps)
    return latest.isoformat().replace("+00:00", "Z")


def summarize_failure_kinds(
    runs: list[dict[str, object]], limit: int = 3
) -> list[dict[str, object]]:
    counter: Counter[str] = Counter()
    for run in runs:
        status_raw = coerce_str(run.get("status"))
        if status_raw is None:
            continue
        status = status_raw.lower()
        if status not in {"fail", "failed", "error"}:
            continue
        kind = coerce_str(run.get("failure_kind")) or "unknown"
        counter[kind] += 1
    most_common = counter.most_common(limit)
    return [
        {"kind": kind, "count": count}
        for kind, count in most_common
    ]


def normalize_flaky_rows(
    rows: list[dict[str, object]], limit: int = 3
) -> list[dict[str, object]]:
    if not rows:
        return []
    sorted_rows = sorted(
        rows,
        key=lambda row: to_float(coerce_str(row.get("score"))) or 0.0,
        reverse=True,
    )
    normalized: list[dict[str, object]] = []
    for idx, row in enumerate(sorted_rows[:limit], start=1):
        attempts_value = row.get("attempts") or row.get("Attempts")
        attempts = 0
        if isinstance(attempts_value, bool):
            attempts = int(attempts_value)
        elif isinstance(attempts_value, int):
            attempts = attempts_value
        elif isinstance(attempts_value, float):
            attempts = int(attempts_value)
        else:
            attempts_str = coerce_str(attempts_value)
            attempts_float = to_float(attempts_str)
            if attempts_float is not None:
                attempts = int(attempts_float)
        normalized.append(
            {
                "rank": idx,
                "canonical_id": (
                    coerce_str(row.get("canonical_id"))
                    or coerce_str(row.get("Canonical ID"))
                    or "-"
                ),
                "attempts": attempts,
                "p_fail": to_float(coerce_str(row.get("p_fail"))),
                "score": to_float(coerce_str(row.get("score"))),
                "as_of": (
                    coerce_str(row.get("as_of"))
                    or coerce_str(row.get("generated_at"))
                ),
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
    failure_kinds: list[dict[str, object]],
    flaky_rows: list[dict[str, object]],
    last_updated: str | None,
    recent_runs: list[dict[str, object]],
) -> dict[str, Any]:
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
        "recent_runs": recent_runs,
    }


def format_flaky_markdown(rows: list[dict[str, object]]) -> list[str]:
    header = "| Rank | Canonical ID | Attempts | p_fail | Score |"
    divider = "|-----:|--------------|---------:|------:|------:|"
    lines = [header, divider]
    if not rows:
        lines.append("| - | データなし | 0 | 0.00 | 0.00 |")
        return lines
    for row in rows:
        p_fail_value = row.get("p_fail")
        p_fail = float(p_fail_value) if isinstance(p_fail_value, int | float) else None
        score_value = row.get("score")
        score = float(score_value) if isinstance(score_value, int | float) else None
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
    totals: dict[str, int],
    pass_rate: float | None,
    failure_kinds: list[dict[str, object]],
    flaky_rows: list[dict[str, object]],
    last_updated: str | None,
    runs_path: Path,
    flaky_path: Path,
) -> list[str]:
    kinds_summary = (
        " / ".join(f"{item['kind']} {item['count']}" for item in failure_kinds)
        if failure_kinds
        else "-"
    )
    pass_rate_args = {
        "pass_rate": format_percentage(pass_rate),
        "passes": totals["passes"],
        "executions": totals["executions"],
    }
    failures_args = {"fails": totals["fails"]}
    errors_args = {"errors": totals["errors"]}
    failure_kinds_args = {"summary": kinds_summary}
    kpi_lines = [
        "| 指標 | 値 |",
        "|------|----|",
        "| Pass Rate | {pass_rate} ({passes}/{executions}) |".format(
            **pass_rate_args
        ),
        "| Failures | {fails} |".format(**failures_args),
        "| Errors | {errors} |".format(**errors_args),
        "| Top Failure Kinds | {summary} |".format(**failure_kinds_args),
        "| ソースJSON | [latest.json](./latest.json) |",
    ]
    lines: list[str] = [
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
        *kpi_lines,
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
    now = dt.datetime.now(dt.UTC)
    window = dt.timedelta(days=max(args.days, 1))
    start = now - window

    runs = load_runs(args.runs) if args.runs.exists() else []
    flaky_rows = load_flaky(args.flaky) if args.flaky.exists() else []

    filtered_runs = filter_by_window(runs, start, now)
    run_history = compute_run_history(runs)
    recent_runs = compute_recent_deltas(run_history, limit=3)
    passes, fails, errors = aggregate_status(filtered_runs)
    failure_kinds = summarize_failure_kinds(filtered_runs)

    selected_flaky = select_flaky_rows(flaky_rows, start, now)
    normalized_flaky = normalize_flaky_rows(selected_flaky)

    last_updated = compute_last_updated(filtered_runs)

    executions = passes + fails + errors
    pass_rate_value = (passes / executions) if executions else None

    payload = build_json_payload(
        generated_at=now,
        window_days=args.days,
        passes=passes,
        fails=fails,
        errors=errors,
        failure_kinds=failure_kinds,
        flaky_rows=normalized_flaky,
        last_updated=last_updated,
        recent_runs=recent_runs,
    )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    args.out_json.write_text(json_text, encoding="utf-8")

    totals = {
        "passes": passes,
        "fails": fails,
        "errors": errors,
        "executions": executions,
    }
    markdown_lines = render_markdown(
        today=now.date(),
        window_days=args.days,
        totals=totals,
        pass_rate=pass_rate_value,
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
