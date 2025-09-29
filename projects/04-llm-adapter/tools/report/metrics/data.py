"""Data loading and aggregation helpers for metrics reports."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from statistics import mean, median

from .utils import coerce_optional_float


def load_metrics(path: Path) -> list[Mapping[str, object]]:
    """Load metrics from a JSON Lines file if it exists."""

    if not path.exists():
        return []
    metrics: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            metrics.append(json.loads(line))
    return metrics


def compute_overview(metrics: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Summarise the overall metrics such as success rate and cost."""

    total = len(metrics)
    if total == 0:
        return {
            "total": 0,
            "success_rate": 0.0,
            "avg_latency": 0.0,
            "median_latency": 0.0,
            "total_cost": 0.0,
            "avg_cost": 0.0,
        }
    latencies = [float(m.get("latency_ms", 0)) for m in metrics]
    costs = [float(m.get("cost_usd", 0.0)) for m in metrics]
    successes = sum(1 for m in metrics if m.get("status") == "ok")
    return {
        "total": total,
        "success_rate": round(successes / total * 100, 2),
        "avg_latency": round(mean(latencies), 2),
        "median_latency": round(median(latencies), 2),
        "total_cost": round(sum(costs), 4),
        "avg_cost": round(mean(costs), 4),
    }


def build_comparison_table(
    metrics: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Aggregate metrics per (provider, model, prompt_id)."""

    groups: dict[tuple[object, object, object], list[Mapping[str, object]]] = {}
    for metric in metrics:
        key = (metric.get("provider"), metric.get("model"), metric.get("prompt_id"))
        groups.setdefault(key, []).append(metric)
    table: list[dict[str, object]] = []
    for (provider, model, prompt_id), rows in sorted(groups.items()):
        attempts = len(rows)
        ok_count = sum(1 for row in rows if row.get("status") == "ok")
        avg_latency = mean(float(row.get("latency_ms", 0)) for row in rows)
        avg_cost = mean(float(row.get("cost_usd", 0.0)) for row in rows)
        diff_rates: list[float] = []
        for row in rows:
            eval_payload = row.get("eval", {})
            if isinstance(eval_payload, Mapping):
                diff = eval_payload.get("diff_rate")
                coerced = coerce_optional_float(diff)
                if coerced is not None:
                    diff_rates.append(coerced)
        avg_diff = mean(diff_rates) if diff_rates else None
        table.append(
            {
                "provider": provider,
                "model": model,
                "prompt_id": prompt_id,
                "attempts": attempts,
                "ok_rate": round(ok_count / attempts * 100, 2) if attempts else 0.0,
                "avg_latency": round(avg_latency, 2) if attempts else 0.0,
                "avg_cost": round(avg_cost, 4) if attempts else 0.0,
                "avg_diff_rate": round(avg_diff, 4) if avg_diff is not None else None,
            }
        )
    return table


def build_latency_histogram_data(
    metrics: Sequence[Mapping[str, object]]
) -> dict[str, list[float]]:
    """Prepare histogram data keyed by provider."""

    hist: dict[str, list[float]] = {}
    for metric in metrics:
        provider = str(metric.get("provider"))
        hist.setdefault(provider, []).append(float(metric.get("latency_ms", 0)))
    return hist


def build_scatter_data(
    metrics: Sequence[Mapping[str, object]]
) -> dict[str, list[dict[str, object]]]:
    """Prepare scatter plot data keyed by provider."""

    scatter: dict[str, list[dict[str, object]]] = {}
    for metric in metrics:
        provider = str(metric.get("provider"))
        scatter.setdefault(provider, []).append(
            {
                "latency": float(metric.get("latency_ms", 0)),
                "cost": float(metric.get("cost_usd", 0.0)),
                "prompt_id": metric.get("prompt_id"),
            }
        )
    return scatter


def build_failure_summary(
    metrics: Sequence[Mapping[str, object]]
) -> tuple[int, list[dict[str, object]]]:
    """Return failure counts and the top three failure kinds."""

    counter: Counter[str] = Counter()
    for metric in metrics:
        failure = metric.get("failure_kind")
        if failure:
            counter[str(failure)] += 1
    total = sum(counter.values())
    summary = [
        {"failure_kind": name, "count": count}
        for name, count in counter.most_common(3)
    ]
    return total, summary


def build_determinism_alerts(
    metrics: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Collect repeated non-deterministic failures."""

    alerts: dict[tuple[object, object, object], int] = {}
    for metric in metrics:
        if metric.get("failure_kind") != "non_deterministic":
            continue
        key = (
            metric.get("provider"),
            metric.get("model"),
            metric.get("prompt_id"),
        )
        alerts[key] = alerts.get(key, 0) + 1
    rows: list[dict[str, object]] = []
    for (provider, model, prompt_id), count in sorted(alerts.items()):
        rows.append(
            {
                "provider": provider,
                "model": model,
                "prompt_id": prompt_id,
                "count": count,
            }
        )
    return rows


def load_baseline_expectations(
    baseline_dir: Path,
) -> list[Mapping[str, object]]:
    """Load baseline expectations from ``*.jsonl`` files and JSON documents."""

    entries: list[Mapping[str, object]] = []
    if not baseline_dir.exists():
        return entries
    for path in sorted(baseline_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if isinstance(data, Mapping):
                    entries.append(data)
    json_path = baseline_dir / "expectations.json"
    if json_path.exists():
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping):
                    entries.append(item)
        elif isinstance(raw, Mapping):
            entries.append(raw)
    return entries


__all__ = [
    "build_comparison_table",
    "build_determinism_alerts",
    "build_failure_summary",
    "build_latency_histogram_data",
    "build_scatter_data",
    "compute_overview",
    "load_baseline_expectations",
    "load_metrics",
]
