"""Data loading and aggregation helpers for metrics reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from statistics import mean, median

from .utils import coerce_optional_float

SUCCESS_STATUSES = {"ok", "success"}

_OPENROUTER_PROVIDER = "openrouter"
_RATE_LIMIT_LABEL = "RateLimitError (429)"
_RETRIABLE_LABEL = "RetriableError (5xx)"
_FAILURE_KIND_MAP = {
    "rate_limit": "RateLimitError",
    "rate_limited": "RateLimitError",
    "ratelimit": "RateLimitError",
    "http_429": "RateLimitError",
    "429": "RateLimitError",
    "retryable": "RetriableError",
    "retryable_error": "RetriableError",
    "retryable_http_error": "RetriableError",
    "http_5xx": "RetriableError",
    "5xx": "RetriableError",
}


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
    successes = sum(
        1
        for m in metrics
        if str(m.get("status", "")).lower() in SUCCESS_STATUSES
    )
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
        ok_count = sum(
            1
            for row in rows
            if str(row.get("status", "")).lower() in SUCCESS_STATUSES
        )
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


def _classify_openrouter_http_failure(metric: Mapping[str, object]) -> str | None:
    error_type = metric.get("error_type")
    if isinstance(error_type, str) and error_type:
        normalized = error_type.strip()
        if normalized in ("RateLimitError", "RetriableError"):
            return normalized
    failure_kind = metric.get("failure_kind")
    if isinstance(failure_kind, str) and failure_kind:
        normalized_kind = failure_kind.strip().lower().replace("-", "_")
        mapped = _FAILURE_KIND_MAP.get(normalized_kind)
        if mapped:
            return mapped
    return None


def build_openrouter_http_failures(
    metrics: Sequence[Mapping[str, object]]
) -> tuple[int, list[dict[str, object]]]:
    """Collect OpenRouter HTTP failures grouped by retryable categories."""

    relevant: list[Mapping[str, object]] = []
    for metric in metrics:
        provider = metric.get("provider")
        if str(provider).lower() != _OPENROUTER_PROVIDER:
            continue
        status = metric.get("status")
        if str(status).lower() != "error":
            continue
        relevant.append(metric)
    total = len(relevant)
    counters = {"RateLimitError": 0, "RetriableError": 0}
    for metric in relevant:
        category = _classify_openrouter_http_failure(metric)
        if category is None:
            continue
        counters[category] += 1
    summary: list[dict[str, object]] = []
    if total > 0:
        bucket_order = [
            ("RateLimitError", _RATE_LIMIT_LABEL),
            ("RetriableError", _RETRIABLE_LABEL),
        ]
        for key, label in bucket_order:
            count = counters[key]
            if count == 0:
                continue
            rate = round(count / total * 100, 2)
            summary.append(
                {
                    "category": key,
                    "label": label,
                    "count": count,
                    "rate": rate,
                }
            )
    summary.sort(key=lambda row: row["count"], reverse=True)
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
    "load_metrics",
    "compute_overview",
    "build_comparison_table",
    "build_latency_histogram_data",
    "build_scatter_data",
    "build_failure_summary",
    "build_openrouter_http_failures",
    "build_determinism_alerts",
    "load_baseline_expectations",
]

