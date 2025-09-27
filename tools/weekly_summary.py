#!/usr/bin/env python3
"""Generate weekly QA summary markdown from run history and flaky ranking."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib
import json
import re
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Iterable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from tools.weekly_summary.__main__ import main as _cli_main
    from tools.weekly_summary.__main__ import parse_args as _cli_parse_args

__all__ = ["parse_args", "main"]

_CLI_MODULE_NAME = "tools.weekly_summary.__main__"
_CLI_MODULE: ModuleType | None = None
_CLI_MODULE_MISSING = False


def _load_cli_module() -> ModuleType | None:
    """Return the CLI implementation module if available."""

    global _CLI_MODULE, _CLI_MODULE_MISSING

    if _CLI_MODULE is not None:
        return _CLI_MODULE
    if _CLI_MODULE_MISSING:
        return None
    try:
        _CLI_MODULE = importlib.import_module(_CLI_MODULE_NAME)
    except ModuleNotFoundError:
        _CLI_MODULE_MISSING = True
        return None
    return _CLI_MODULE

ISO_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})")


def _parse_args_impl(argv: Iterable[str] | None = None) -> argparse.Namespace:
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
    args = None if argv is None else list(argv)
    return parser.parse_args(args)


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


def aggregate_status(runs: Iterable[dict]) -> tuple[int, int, int]:
    passes = fails = errors = 0
    for run in runs:
        status = (run.get("status") or "").lower()
        if status == "pass":
            passes += 1
        elif status in {"fail", "failed"}:
            fails += 1
        elif status == "error":
            errors += 1
    return passes, fails, errors


def compute_failure_top(counter: Counter[str], top_n: int = 3) -> str:
    if not counter:
        return "-"
    parts: List[str] = []
    for name, count in counter.most_common(top_n):
        display = name if name else "unknown"
        parts.append(f"{display} {count}")
    return " / ".join(parts)


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


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def format_percentage(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_table(rows: List[dict]) -> List[str]:
    header = "| Rank | Canonical ID | Attempts | p_fail | Score |"
    divider = "|-----:|--------------|---------:|------:|------:|"
    body: List[str] = [header, divider]
    for idx, row in enumerate(rows, start=1):
        attempts = row.get("attempts") or row.get("Attempts") or "0"
        p_fail = to_float(row.get("p_fail"))
        score = to_float(row.get("score"))
        body.append(
            "| {rank} | {cid} | {attempts} | {p_fail:.2f} | {score:.2f} |".format(
                rank=idx,
                cid=row.get("canonical_id", "-"),
                attempts=int(float(attempts)) if attempts else 0,
                p_fail=p_fail or 0.0,
                score=score or 0.0,
            )
        )
    if len(body) == 2:
        body.append("| - | データなし | 0 | 0.00 | 0.00 |")
    return body


def week_over_week_notes(current_rows: List[dict], previous_rows: List[dict]) -> tuple[List[str], List[str]]:
    current_ids = [row.get("canonical_id") for row in current_rows if row.get("canonical_id")]
    previous_ids = [row.get("canonical_id") for row in previous_rows if row.get("canonical_id")]
    entered = [cid for cid in current_ids if cid not in previous_ids]
    exited = [cid for cid in previous_ids if cid not in current_ids]
    return entered, exited


def build_front_matter(today: dt.date, days: int) -> List[str]:
    return [
        "---",
        "layout: default",
        f"title: Weekly QA Summary — {today.isoformat()}",
        f"description: 直近{days}日間のQA状況サマリ",
        "---",
        "",
    ]


def ensure_front_matter(lines: List[str], today: dt.date, days: int) -> List[str]:
    stripped = list(lines)
    if stripped and stripped[0] == "---":
        try:
            closing = stripped.index("---", 1)
        except ValueError:
            stripped = stripped[1:]
        else:
            stripped = stripped[closing + 1 :]
        while stripped and stripped[0] == "":
            stripped.pop(0)
    return build_front_matter(today, days) + stripped


def fallback_write(out_path: Path, today: dt.date, days: int) -> None:
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8").splitlines()
    else:
        existing = []

    if not existing:
        placeholder = [
            f"# Weekly QA Summary — {today.isoformat()}",
            "",
            f"## Overview (last {days} days)",
            "- TotalTests: 0",
            "- PassRate: N/A",
            "- NewDefects: 0",
            "- TopFailureKinds: -",
            "",
            "## Top Flaky (score)",
            "| Rank | Canonical ID | Attempts | p_fail | Score |",
            "|-----:|--------------|---------:|------:|------:|",
            "| - | データなし | 0 | 0.00 | 0.00 |",
            "",
            "## Notes",
            "- データソースが見つからなかったため前回出力を保持しました。",
            "",
            "<details><summary>Method</summary>",
            "データソース: runs.jsonl, flaky_rank.csv / 期間: 直近7日 / 再計算: 毎週月曜 09:00 JST",
            "</details>",
            "",
        ]
        out_path.write_text(
            "\n".join(build_front_matter(today, days) + placeholder) + "\n",
            encoding="utf-8",
        )
        return

    updated = ensure_front_matter(existing, today, days)
    title_line = f"# Weekly QA Summary — {today.isoformat()}"
    for idx, line in enumerate(updated):
        if line.startswith("# Weekly QA Summary"):
            updated[idx] = title_line
            break
    else:
        updated.append(title_line)
        updated.append("")

    out_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _main_impl() -> None:
    args = _parse_args_impl()
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

    passes, fails, errors = aggregate_status(current_runs)
    prev_passes, prev_fails, prev_errors = aggregate_status(previous_runs)

    total_tests = passes + fails + errors
    prev_total = prev_passes + prev_fails + prev_errors

    pass_rate = (passes / total_tests) if total_tests else None
    prev_pass_rate = (prev_passes / prev_total) if prev_total else None

    failure_counter: Counter[str] = Counter()
    for run in current_runs:
        status = (run.get("status") or "").lower()
        if status not in {"fail", "failed", "error"}:
            continue
        kind = run.get("failure_kind") or "unknown"
        failure_counter[kind] += 1

    top_failure = compute_failure_top(failure_counter)
    new_defects = count_new_defects(defect_dates, current_start.date())

    current_flaky = select_flaky_rows(flaky_rows, current_start, now)
    previous_flaky = select_flaky_rows(flaky_rows, previous_start, current_start)

    def sort_flaky(rows: List[dict]) -> List[dict]:
        return sorted(rows, key=lambda row: to_float(row.get("score")) or 0.0, reverse=True)

    current_flaky_sorted = sort_flaky(current_flaky)[:5]
    previous_flaky_sorted = sort_flaky(previous_flaky)[:5]

    table_lines = format_table(current_flaky_sorted)

    entered, exited = week_over_week_notes(current_flaky_sorted, previous_flaky_sorted)
    wow_delta = None
    if pass_rate is not None and prev_pass_rate is not None:
        wow_delta = (pass_rate - prev_pass_rate) * 100

    notes: List[str] = []
    if wow_delta is not None:
        notes.append(
            f"PassRate WoW: {wow_delta:+.2f}pp (prev {prev_pass_rate * 100:.2f}%)."
        )
    elif pass_rate is not None:
        notes.append(f"PassRate: {pass_rate * 100:.2f}% (過去週データ不足)")
    else:
        notes.append("PassRate算出対象となるテストがありません。")

    if entered:
        notes.append("Top Flaky 新規: " + ", ".join(entered))
    if exited:
        notes.append("Top Flaky 離脱: " + ", ".join(exited))
    if not notes:
        notes.append("特記事項なし。")

    markdown_lines: List[str] = [
        f"# Weekly QA Summary — {today.isoformat()}",
        "",
        f"## Overview (last {args.days} days)",
        f"- TotalTests: {total_tests}",
        f"- PassRate: {format_percentage(pass_rate)}",
        f"- NewDefects: {new_defects}",
        f"- TopFailureKinds: {top_failure}",
        "",
        "## Top Flaky (score)",
        *table_lines,
        "",
        "## Week-over-Week",
        f"- PassRate Δ: {wow_delta:+.2f}pp" if wow_delta is not None else "- PassRate Δ: N/A",
        f"- Entered: {', '.join(entered) if entered else 'なし'}",
        f"- Exited: {', '.join(exited) if exited else 'なし'}",
        "",
        "## Notes",
    ]
    markdown_lines.extend(f"- {note}" for note in notes)
    markdown_lines.extend(
        [
            "",
            "<details><summary>Method</summary>",
            f"データソース: {args.runs} / {args.flaky} / 欠陥: {args.defects}",
            f"期間: 直近{args.days}日 / 比較対象: その前の{args.days}日",
            "再計算: 毎週月曜 09:00 JST (GitHub Actions)",
            "</details>",
            "",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = build_front_matter(today, args.days) + markdown_lines
    out_path.write_text("\n".join(content) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    module = _load_cli_module()
    if module is not None:
        parse = getattr(module, "parse_args", None)
        if callable(parse):
            if argv is None:
                return parse()
            return parse(argv)
    return _parse_args_impl(argv)


def main() -> None:
    module = _load_cli_module()
    if module is not None:
        entry = getattr(module, "main", None)
        if callable(entry):
            entry()
            return
    _main_impl()


if __name__ == "__main__":  # pragma: no cover
    main()
