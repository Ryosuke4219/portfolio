from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from . import (
    compute_summary,
    extract_defect_dates,
    fallback_write,
    filter_by_window,
    load_flaky,
    load_runs,
    select_flaky_rows,
    build_markdown,
    write_summary,
)


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = parse_args()

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

    current_flaky = select_flaky_rows(flaky_rows, current_start, now)
    previous_flaky = select_flaky_rows(flaky_rows, previous_start, current_start)

    summary = compute_summary(
        today=today,
        days=args.days,
        current_window_start=current_start,
        current_runs=current_runs,
        previous_runs=previous_runs,
        defect_dates=defect_dates,
        current_flaky=current_flaky,
        previous_flaky=previous_flaky,
    )

    markdown_lines = build_markdown(today, args.days, summary)
    method_lines = [
        "<details><summary>Method</summary>",
        f"データソース: {args.runs} / {args.flaky} / 欠陥: {args.defects}",
        f"期間: 直近{args.days}日 / 比較対象: その前の{args.days}日",
        "再計算: 毎週月曜 09:00 JST (GitHub Actions)",
        "</details>",
    ]

    write_summary(out_path, today, args.days, markdown_lines, method_lines=method_lines)


if __name__ == "__main__":  # pragma: no cover
    main()
