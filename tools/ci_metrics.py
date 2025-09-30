"""Utilities for deriving CI metrics from run history."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
import datetime as dt
from pathlib import Path

import weekly_summary
from weekly_summary import coerce_str, load_runs

PASS_STATUSES = {"pass", "passed"}
FAIL_STATUSES = {"fail", "failed"}
ERROR_STATUSES = {"error", "errored"}


@dataclass
class RunRecord:
    run_id: str
    timestamp: dt.datetime | None
    records: list[dict]


@dataclass
class RunMetrics:
    run_id: str
    timestamp: dt.datetime | None
    total: int
    passes: int
    fails: int
    errors: int
    pass_rate: float | None
    flaky_count: int


def normalize_status(value: str | None) -> str:
    status = (value or "").strip().lower()
    if status in PASS_STATUSES:
        return "pass"
    if status in FAIL_STATUSES:
        return "fail"
    if status in ERROR_STATUSES:
        return "error"
    return "other"


def _group_runs(runs: Iterable[dict]) -> list[RunRecord]:
    grouped: dict[str, RunRecord] = {}
    for record in runs:
        run_id = coerce_str(record.get("run_id"))
        if not run_id:
            continue
        ts = weekly_summary.parse_iso8601(coerce_str(record.get("ts")))
        if run_id not in grouped:
            grouped[run_id] = RunRecord(run_id=run_id, timestamp=ts, records=[record])
        else:
            grouped_record = grouped[run_id]
            grouped_record.records.append(record)
            if ts is None:
                continue
            if grouped_record.timestamp is None or ts < grouped_record.timestamp:
                grouped_record.timestamp = ts
    records = list(grouped.values())
    records.sort(
        key=lambda item: (
            item.timestamp or dt.datetime.min.replace(tzinfo=dt.UTC),
            item.run_id,
        )
    )
    return records


def compute_run_history(
    runs: Iterable[dict], *, window_size: int = 5
) -> list[RunMetrics]:
    grouped_runs = _group_runs(runs)
    if not grouped_runs:
        return []

    history: dict[str, deque[str]] = {}
    flaky_flags: dict[str, bool] = {}
    current_flaky_total = 0

    metrics: list[RunMetrics] = []
    for run in grouped_runs:
        total = passes = fails = errors = 0
        for record in sorted(
            run.records,
            key=lambda item: weekly_summary.parse_iso8601(coerce_str(item.get("ts")))
            or run.timestamp
            or dt.datetime.min.replace(tzinfo=dt.UTC),
        ):
            total += 1
            status = normalize_status(coerce_str(record.get("status")))
            if status == "pass":
                passes += 1
            elif status == "fail":
                fails += 1
            elif status == "error":
                errors += 1

            canonical_id = coerce_str(record.get("canonical_id"))
            if not canonical_id:
                continue
            bucket = history.get(canonical_id)
            if bucket is None:
                bucket = deque(maxlen=max(window_size, 1))
                history[canonical_id] = bucket
            bucket.append(status)

            previous_flag = flaky_flags.get(canonical_id, False)
            status_set = {item for item in bucket if item in {"pass", "fail", "error"}}
            has_pass = "pass" in status_set
            has_failure = bool(status_set & {"fail", "error"})
            is_flaky = has_pass and has_failure
            flaky_flags[canonical_id] = is_flaky
            if is_flaky and not previous_flag:
                current_flaky_total += 1
            elif previous_flag and not is_flaky:
                current_flaky_total = max(0, current_flaky_total - 1)

        pass_rate = (passes / total) if total else None
        metrics.append(
            RunMetrics(
                run_id=run.run_id,
                timestamp=run.timestamp,
                total=total,
                passes=passes,
                fails=fails,
                errors=errors,
                pass_rate=pass_rate,
                flaky_count=current_flaky_total,
            )
        )

    return metrics


def compute_recent_deltas(history: list[RunMetrics], limit: int = 3) -> list[dict]:
    if not history:
        return []

    recent: list[dict] = []
    start_index = max(0, len(history) - max(limit, 0))
    for idx in range(start_index, len(history)):
        entry = history[idx]
        prev = history[idx - 1] if idx > 0 else None
        pass_delta: float | None = None
        flaky_delta: int | None = None
        if prev and entry.pass_rate is not None and prev.pass_rate is not None:
            pass_delta = entry.pass_rate - prev.pass_rate
        if prev is not None:
            flaky_delta = entry.flaky_count - prev.flaky_count
        timestamp_iso: str | None = None
        if entry.timestamp is not None:
            timestamp_iso = entry.timestamp.isoformat().replace("+00:00", "Z")
        recent.append(
            {
                "run_id": entry.run_id,
                "ts": timestamp_iso,
                "pass_rate": entry.pass_rate,
                "pass_rate_delta": pass_delta,
                "flaky_count": entry.flaky_count,
                "flaky_delta": flaky_delta,
            }
        )
    return recent


def load_run_history(path: Path, *, window_size: int = 5) -> list[RunMetrics]:
    runs = load_runs(path)
    return compute_run_history(runs, window_size=window_size)


__all__ = [
    "RunMetrics",
    "compute_run_history",
    "compute_recent_deltas",
    "load_run_history",
]
