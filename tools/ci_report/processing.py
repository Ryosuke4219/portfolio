"""Data aggregation helpers for CI report generation."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Iterable

from tools.weekly_summary import coerce_str, parse_iso8601, to_float


def compute_last_updated(runs: Iterable[dict[str, object]]) -> str | None:
    """Return the latest timestamp in ISO 8601 format without timezone suffix."""
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
    runs: Iterable[dict[str, object]], limit: int = 3
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
    rows: Iterable[dict[str, object]], limit: int = 3
) -> list[dict[str, object]]:
    materialized = list(rows)
    if not materialized:
        return []
    sorted_rows = sorted(
        materialized,
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
