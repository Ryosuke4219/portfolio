"""Rendering utilities for CI report outputs."""
from __future__ import annotations

from collections.abc import Iterable
import datetime as dt
from pathlib import Path
from typing import Any

from tools import weekly_summary


def build_json_payload(
    *,
    generated_at: dt.datetime,
    window_days: int,
    passes: int,
    fails: int,
    errors: int,
    failure_kinds: Iterable[dict[str, object]],
    flaky_rows: Iterable[dict[str, object]],
    last_updated: str | None,
    recent_runs: Iterable[dict[str, object]],
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
        "failure_kinds": list(failure_kinds),
        "top_flaky": list(flaky_rows),
        "last_updated": last_updated,
        "recent_runs": list(recent_runs),
    }


def _format_flaky_markdown(rows: Iterable[dict[str, object]]) -> list[str]:
    materialized = list(rows)
    header = "| Rank | Canonical ID | Attempts | p_fail | Score |"
    divider = "|-----:|--------------|---------:|------:|------:|"
    lines = [header, divider]
    if not materialized:
        lines.append("| - | データなし | 0 | 0.00 | 0.00 |")
        return lines
    for row in materialized:
        p_fail_value = row.get("p_fail")
        p_fail = weekly_summary.to_float(p_fail_value)
        score_value = row.get("score")
        score = weekly_summary.to_float(score_value)
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
    failure_kinds: Iterable[dict[str, object]],
    flaky_rows: Iterable[dict[str, object]],
    last_updated: str | None,
    runs_path: Path,
    flaky_path: Path,
) -> list[str]:
    kinds = list(failure_kinds)
    flaky = list(flaky_rows)
    kinds_summary = (
        " / ".join(f"{item['kind']} {item['count']}" for item in kinds)
        if kinds
        else "-"
    )
    pass_rate_args = {
        "pass_rate": weekly_summary.format_percentage(pass_rate),
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
        *_format_flaky_markdown(flaky),
        "",
        "<details><summary>Generation</summary>",
        f"Source: runs={runs_path} / flaky={flaky_path}",
        f"Window: {window_days} days / Executions: {totals['executions']}",
        "Automation: tools/generate_ci_report.py (GitHub Actions)",
        "</details>",
        "",
    ]
    return lines


__all__ = ["build_json_payload", "render_markdown"]
