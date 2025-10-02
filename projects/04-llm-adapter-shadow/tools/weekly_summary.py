from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean, median
from typing import Any


@dataclass(slots=True)
class Summary:
    total_runs: int
    success_count: int
    failure_count: int
    failure_rate: float
    latencies: list[float]
    outcomes: Counter[str]
    diff_kinds: Counter[str]


def _load_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _normalize_outcome(record: Mapping[str, Any]) -> str:
    outcome = record.get("outcome")
    if isinstance(outcome, str) and outcome.strip():
        return outcome.strip().lower()
    status = record.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()
    return "unknown"


def _collect(path: Path) -> Summary:
    latencies: list[float] = []
    outcomes: Counter[str] = Counter()
    diff_counts: Counter[str] = Counter()
    total = 0
    success = 0

    for record in _load_records(path):
        event = record.get("event")
        if event == "run_metric":
            outcome = _normalize_outcome(record)
            outcomes[outcome] += 1
            total += 1
            if outcome == "success":
                success += 1
            latency = record.get("latency_ms")
            if isinstance(latency, (int, float)) and latency >= 0:  # noqa: UP038
                latencies.append(float(latency))
        elif event == "shadow_diff":
            diff_kind = record.get("diff_kind")
            if isinstance(diff_kind, str) and diff_kind:
                diff_counts[diff_kind] += 1

    failure = total - success
    rate = failure / total if total else 0.0
    return Summary(total, success, failure, rate, latencies, outcomes, diff_counts)


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _format_number(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def _render(summary: Summary) -> str:
    latencies = summary.latencies
    avg = mean(latencies) if latencies else None
    med = median(latencies) if latencies else None
    p95 = _percentile(latencies, 0.95) if latencies else None

    lines = [
        "# Weekly Shadow Summary",
        "",
        "## Overview",
        f"- Total Runs: {summary.total_runs}",
        f"- Successes: {summary.success_count}",
        f"- Failures: {summary.failure_count}",
        f"- Failure Rate: {summary.failure_rate * 100:.2f}%",
        "",
        "## Latency (ms)",
        f"- Average: {_format_number(avg)}",
        f"- Median: {_format_number(med)}",
        f"- P95: {_format_number(p95)}",
        "",
        "## Outcomes",
    ]

    if summary.outcomes:
        lines.append("| Outcome | Count |")
        lines.append("|---------|-------|")
        for outcome, count in sorted(
            summary.outcomes.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"| {outcome} | {count} |")
    else:
        lines.append("- No run_metric events")

    lines.extend(["", "## Shadow Diff Kinds"])
    if summary.diff_kinds:
        lines.append("| diff_kind | Count |")
        lines.append("|-----------|-------|")
        for diff_kind, count in sorted(
            summary.diff_kinds.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"| {diff_kind} | {count} |")
    else:
        lines.append("- No shadow_diff events")

    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a weekly shadow summary")
    parser.add_argument("--input", required=True, help="Path to runs-metrics.jsonl")
    parser.add_argument("--output", required=True, help="Path to output markdown")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    summary = _collect(input_path)
    markdown = _render(summary)
    output_path.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
