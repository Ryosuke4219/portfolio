from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_PREV_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([0-9]+(?:\.[0-9]+)?)%")


def _load_jsonl(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        raise SystemExit(f"metrics file not found: {path}")
    rows: list[Mapping[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            trimmed = raw.strip()
            if not trimmed:
                continue
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise SystemExit(f"invalid JSON in {path}: {exc}") from exc
            if isinstance(parsed, Mapping):
                rows.append(parsed)
    return rows


def _aggregate(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, float, int | None]]:
    totals: dict[str, list[Any]] = defaultdict(lambda: [0, 0, []])
    for row in rows:
        if row.get("event") != "shadow_diff":
            continue
        provider = row.get("shadow_provider")
        if not isinstance(provider, str) or not provider:
            continue
        bucket = totals[provider]
        bucket[0] += 1
        if row.get("shadow_outcome") != "success":
            bucket[1] += 1
        latency = row.get("shadow_latency_ms")
        if isinstance(latency, (int, float)):
            bucket[2].append(float(latency))
    return sorted([
        (
            provider,
            round((float(fails) / float(count)) * 100.0, 1),
            int(round(sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]))
            if latencies
            else None,
        )
        for provider, (count, fails, latencies) in totals.items()
        if count
    ], key=lambda item: (-item[1], item[0]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate shadow metrics into markdown")
    parser.add_argument("--input", required=True, help="Path to runs-metrics JSONL")
    parser.add_argument("--output", default="docs/weekly-summary.md", help="Destination markdown file")
    parser.add_argument("--prev", help="Previous markdown to diff against")
    args = parser.parse_args(argv)
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    prev_path = Path(args.prev).expanduser().resolve() if args.prev else None

    summary = _aggregate(_load_jsonl(input_path))
    previous: dict[str, float] = {}
    if prev_path and prev_path.exists():
        for line in prev_path.read_text(encoding="utf-8").splitlines():
            match = _PREV_RE.match(line)
            if match:
                provider, rate_str = match.groups()
                previous[provider.strip()] = float(rate_str)

    rows = [
        "| {provider} | {rate:.1f}% | {delta} | {latency} |".format(
            provider=provider,
            rate=rate,
            delta="n/a" if previous.get(provider) is None else f"{rate - previous[provider]:+.1f}pp",
            latency=str(latency) if latency is not None else "n/a",
        )
        for provider, rate, latency in summary
    ]
    markdown = "\n".join(
        [
            "# Weekly Shadow Summary",
            "",
            "| Provider | Failure Rate | Δ vs Prev | P95 Latency (ms) |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
