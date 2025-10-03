#!/usr/bin/env python3
"""Generate CI reliability snapshot in Markdown and JSON."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def _import_module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:  # pragma: no cover - fallback for direct execution
        _ensure_repo_root_on_path()
        return importlib.import_module(name)


ci_metrics = _import_module("tools.ci_metrics")
weekly_summary = _import_module("tools.weekly_summary")
ci_processing = _import_module("tools.ci_report.processing")
ci_rendering = _import_module("tools.ci_report.rendering")


compute_recent_deltas = ci_metrics.compute_recent_deltas
compute_run_history = ci_metrics.compute_run_history
compute_last_updated = ci_processing.compute_last_updated
normalize_flaky_rows = ci_processing.normalize_flaky_rows
summarize_failure_kinds = ci_processing.summarize_failure_kinds
build_json_payload = ci_rendering.build_json_payload
render_markdown = ci_rendering.render_markdown


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

    runs = weekly_summary.load_runs(args.runs) if args.runs.exists() else []
    flaky_rows = weekly_summary.load_flaky(args.flaky) if args.flaky.exists() else []

    filtered_runs = weekly_summary.filter_by_window(runs, start, now)
    run_history = compute_run_history(runs)
    recent_runs = compute_recent_deltas(run_history, limit=3)
    passes, fails, errors = weekly_summary.aggregate_status(filtered_runs)
    failure_kinds = summarize_failure_kinds(filtered_runs)

    selected_flaky = weekly_summary.select_flaky_rows(flaky_rows, start, now)
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
