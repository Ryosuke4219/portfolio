"""Utilities for generating LLM Adapter metric reports."""

from .cli import generate_report, main
from .data import (
    build_comparison_table,
    build_determinism_alerts,
    build_failure_summary,
    build_latency_histogram_data,
    build_scatter_data,
    compute_overview,
    load_baseline_expectations,
    load_metrics,
)
from .html_report import render_html
from .regression_summary import build_regression_summary
from .weekly_summary import update_weekly_summary

__all__ = [
    "build_comparison_table",
    "build_determinism_alerts",
    "build_failure_summary",
    "build_latency_histogram_data",
    "build_regression_summary",
    "build_scatter_data",
    "compute_overview",
    "generate_report",
    "load_baseline_expectations",
    "load_metrics",
    "main",
    "render_html",
    "update_weekly_summary",
]
