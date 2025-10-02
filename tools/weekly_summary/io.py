# ruff: noqa: I001

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

from collections.abc import Iterable

ISO_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})")

__all__ = [
    "parse_iso8601",
    "coerce_str",
    "load_runs",
    "load_flaky",
    "filter_by_window",
]


def parse_iso8601(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value)
    except ValueError:
        match = ISO_RE.match(value)
        if match:
            return dt.datetime.fromisoformat(match.group("date") + "T00:00:00+00:00")
    return None


def coerce_str(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float, bool)):  # noqa: UP038 bool is intentionally grouped with numeric types.
        return str(value)
    return None


def load_runs(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    runs: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            runs.append(record)
    return runs


def load_flaky(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    return rows


def filter_by_window(
    items: Iterable[dict[str, object]], start: dt.datetime, end: dt.datetime
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item in items:
        ts_value = coerce_str(item.get("ts"))
        ts = parse_iso8601(ts_value)
        if ts is None:
            continue
        if start <= ts < end:
            results.append(item)
    return results
