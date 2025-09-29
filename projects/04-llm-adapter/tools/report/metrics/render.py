"""Facade exports for metrics rendering helpers."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping, Sequence

from .html_report import render_html as _render_html
from .regression_summary import build_regression_summary as _build_regression_summary
from .weekly_summary import update_weekly_summary as _update_weekly_summary


def build_regression_summary(
    metrics: Sequence[Mapping[str, object]], golden_dir: Path | None
) -> str:
    """Proxy to :func:`regression_summary.build_regression_summary`."""
    return _build_regression_summary(metrics, golden_dir)


def render_html(
    overview: Mapping[str, object],
    comparison_table: Sequence[Mapping[str, object]],
    hist_data: Mapping[str, Sequence[float]],
    scatter_data: Mapping[str, Sequence[Mapping[str, object]]],
    regression_html: str,
    failure_total: int,
    failure_summary: Sequence[Mapping[str, object]],
    determinism_alerts: Sequence[Mapping[str, object]],
) -> str:
    """Proxy to :func:`html_report.render_html`."""
    return _render_html(
        overview,
        comparison_table,
        hist_data,
        scatter_data,
        regression_html,
        failure_total,
        failure_summary,
        determinism_alerts,
    )


def update_weekly_summary(
    weekly_path: Path,
    failure_total: int,
    failure_summary: Sequence[Mapping[str, object]],
) -> None:
    """Proxy to :func:`weekly_summary.update_weekly_summary`."""
    _update_weekly_summary(weekly_path, failure_total, failure_summary)


__all__ = [
    "build_regression_summary",
    "render_html",
    "update_weekly_summary",
]
