"""CLI entry point for the weekly summary generator."""

from __future__ import annotations

import argparse
import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Iterable, List

from . import (
    aggregate_status,
    build_front_matter,
    compute_failure_top,
    count_new_defects,
    extract_defect_dates,
    fallback_write,
    filter_by_window,
    format_percentage,
    format_table,
    load_flaky,
    load_runs,
    select_flaky_rows,
    to_float,
    week_over_week_notes,
)

__all__ = ["parse_args", "main"]


def _parse_args_impl(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly QA summary")
    parser.add_argument("--runs", type=Path, required=True, help="Path to runs.jsonl")
    parser.add_argument("--flaky", type=Path, required=True, help="Path to flaky_rank.csv")
    parser.add_argument("--out", type=Path, required=True, help="Output markdown path")
    parser.add_argument("--days", type=int, default=7, help="Window size in days")
    parser.add_argument(
        "--defects",
        type=Path,
        default=Path("docs/defect-report-sample.md"),
        help="Path to defect reports used for counting new defects",
    )
    args = None if argv is None else list(argv)
    return parser.parse_args(args)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    return _parse_args_impl(argv)


def _main_impl() -> None:
    args = _parse_args_impl()
    out_path: Path = args.out
    today = dt.datetime.now(dt.timezone.utc).date()

    if not args.runs.exists() or not args.flaky.exists():
        fallback_write(out_path, today, args.days)
        return

    runs = load_runs(args.runs)
    flaky_rows = load_flaky(args.flaky)
    defect_dates = extract_defect_dates(args.defects)

    now = dt.datetime.now(dt.timezone.utc)
    window = dt.timedelta(days=max(args.days, 1))
    current_start = now - window
    previous_start = now - window * 2

    current_runs = filter_by_window(runs, current_start, now)
    previous_runs = filter_by_window(runs, previous_start, current_start)

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
    new_defects = count_new_defects(defect_dates, current_start.date())

    current_flaky = select_flaky_rows(flaky_rows, current_start, now)
    previous_flaky = select_flaky_rows(flaky_rows, previous_start, current_start)

    def sort_flaky(rows: List[dict]) -> List[dict]:
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
        notes.append(
            f"PassRate WoW: {wow_delta:+.2f}pp (prev {prev_pass_rate * 100:.2f}%)."
        )
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

    markdown_lines: List[str] = [
        f"# Weekly QA Summary — {today.isoformat()}",
        "",
        f"## Overview (last {args.days} days)",
        f"- TotalTests: {total_tests}",
        f"- PassRate: {format_percentage(pass_rate)}",
        f"- NewDefects: {new_defects}",
        f"- TopFailureKinds: {top_failure}",
        "",
        "## Top Flaky (score)",
        *table_lines,
        "",
        "## Week-over-Week",
        f"- PassRate Δ: {wow_delta:+.2f}pp" if wow_delta is not None else "- PassRate Δ: N/A",
        f"- Entered: {', '.join(entered) if entered else 'なし'}",
        f"- Exited: {', '.join(exited) if exited else 'なし'}",
        "",
        "## Notes",
    ]
    markdown_lines.extend(f"- {note}" for note in notes)
    markdown_lines.extend(
        [
            "",
            "<details><summary>Method</summary>",
            f"データソース: {args.runs} / {args.flaky} / 欠陥: {args.defects}",
            f"期間: 直近{args.days}日 / 比較対象: その前の{args.days}日",
            "再計算: 毎週月曜 09:00 JST (GitHub Actions)",
            "</details>",
            "",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = build_front_matter(today, args.days) + markdown_lines
    out_path.write_text("\n".join(content) + "\n", encoding="utf-8")


def main() -> None:
    _main_impl()


if __name__ == "__main__":  # pragma: no cover
    main()

