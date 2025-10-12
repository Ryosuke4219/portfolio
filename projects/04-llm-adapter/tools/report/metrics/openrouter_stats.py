"""CLI for aggregating OpenRouter HTTP failure metrics."""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime
import json
from pathlib import Path

from .data import build_openrouter_http_failures, load_metrics
from .utils import parse_iso_ts

_OUTPUT_JSON = "openrouter_http_failures.json"
_OUTPUT_JSONL = "openrouter_http_failures.jsonl"


def _filter_since(
    metrics: Sequence[Mapping[str, object]],
    since: datetime | None,
) -> list[Mapping[str, object]]:
    if since is None:
        return list(metrics)
    filtered: list[Mapping[str, object]] = []
    for metric in metrics:
        metric_ts = parse_iso_ts(metric.get("ts"))
        if metric_ts >= since:
            filtered.append(metric)
    return filtered


def _write_outputs(out_dir: Path, total: int, rows: Sequence[Mapping[str, object]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / _OUTPUT_JSON
    summary_path.write_text(
        json.dumps({"total": total, "rows": list(rows)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    jsonl_path = out_dir / _OUTPUT_JSONL
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenRouter HTTP failure metrics 集計")
    parser.add_argument("--metrics", required=True, help="runs-metrics.jsonl のパス")
    parser.add_argument("--out", required=True, help="集計結果の出力ディレクトリ")
    parser.add_argument("--since", default=None, help="この日時以降のメトリクスのみ集計 (ISO 8601)")
    args = parser.parse_args(argv)

    metrics_path = Path(args.metrics).expanduser()
    out_dir = Path(args.out).expanduser()
    since = parse_iso_ts(args.since) if args.since else None

    metrics = load_metrics(metrics_path)
    scoped_metrics = _filter_since(metrics, since)
    total, rows = build_openrouter_http_failures(scoped_metrics)
    _write_outputs(out_dir, total, rows)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
