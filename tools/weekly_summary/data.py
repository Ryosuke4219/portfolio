from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List, Optional

import datetime as dt
import re

ISO_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})")


def parse_iso8601(value: Optional[str]) -> Optional[dt.datetime]:
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


def load_runs(path: Path) -> List[dict]:
    if not path.exists():
        return []
    runs: List[dict] = []
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


def load_flaky(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    return rows


def filter_by_window(items: Iterable[dict], start: dt.datetime, end: dt.datetime) -> List[dict]:
    results: List[dict] = []
    for item in items:
        ts = parse_iso8601(item.get("ts"))
        if ts is None:
            continue
        if start <= ts < end:
            results.append(item)
    return results


def extract_defect_dates(path: Path) -> List[dt.date]:
    if not path.exists():
        return []
    dates: List[dt.date] = []
    pattern = re.compile(r"-\s*起票日:\s*(\d{4}-\d{2}-\d{2})")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = pattern.search(line)
            if match:
                try:
                    dates.append(dt.date.fromisoformat(match.group(1)))
                except ValueError:
                    continue
    return dates


def count_new_defects(defect_dates: Iterable[dt.date], start: dt.date) -> int:
    return sum(1 for value in defect_dates if value >= start)


def select_flaky_rows(rows: List[dict], start: dt.datetime, end: dt.datetime) -> List[dict]:
    if not rows:
        return []
    selected: List[dict] = []
    for row in rows:
        as_of_raw = row.get("as_of") or row.get("generated_at")
        as_of_dt = parse_iso8601(as_of_raw) if as_of_raw else None
        if as_of_dt is None:
            selected.append(row)
            continue
        if start.date() <= as_of_dt.date() < end.date():
            selected.append(row)
    return selected
