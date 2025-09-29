"""Command line entry points for the metrics report generator."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .data import (
    build_comparison_table,
    build_determinism_alerts,
    build_failure_summary,
    build_latency_histogram_data,
    build_scatter_data,
    compute_overview,
    load_metrics,
)
from .html_report import render_html
from .regression_summary import build_regression_summary
from .weekly_summary import update_weekly_summary


def generate_report(
    metrics_path: Path,
    golden_dir: Path | None,
    out_path: Path,
    weekly_summary_path: Path | None = None,
) -> None:
    metrics = load_metrics(metrics_path)
    overview = compute_overview(metrics)
    comparison_table = build_comparison_table(metrics)
    hist_data = build_latency_histogram_data(metrics)
    scatter_data = build_scatter_data(metrics)
    regression_html = build_regression_summary(metrics, golden_dir)
    failure_total, failure_summary = build_failure_summary(metrics)
    determinism_alerts = build_determinism_alerts(metrics)
    html = render_html(
        overview,
        comparison_table,
        hist_data,
        scatter_data,
        regression_html,
        failure_total,
        failure_summary,
        determinism_alerts,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    if weekly_summary_path is not None:
        update_weekly_summary(weekly_summary_path, failure_total, failure_summary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JSONL メトリクスから HTML を生成")
    parser.add_argument("--metrics", required=True, help="runs-metrics.jsonl のパス")
    parser.add_argument("--golden", default=None, help="ゴールデンディレクトリ")
    parser.add_argument("--out", required=True, help="出力 HTML パス")
    parser.add_argument("--weekly-summary", default=None, help="週次サマリ Markdown の出力パス")
    args = parser.parse_args(argv)

    metrics_path = Path(args.metrics).expanduser().resolve()
    golden_dir = Path(args.golden).expanduser().resolve() if args.golden else None
    out_path = Path(args.out).expanduser().resolve()
    weekly_summary = (
        Path(args.weekly_summary).expanduser().resolve()
        if args.weekly_summary
        else None
    )

    generate_report(metrics_path, golden_dir, out_path, weekly_summary)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
