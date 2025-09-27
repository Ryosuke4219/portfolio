"""Shared helpers for metrics report processing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Mapping, Sequence, Tuple


def parse_iso_ts(value: object) -> datetime:
    """Parse ISO formatted timestamps and normalize to timezone aware UTC."""

    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def coerce_optional_float(value: object) -> float | None:
    """Best-effort conversion of optional numeric values to ``float``."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def latest_metrics_by_key(
    metrics: Sequence[Mapping[str, object]]
) -> Dict[Tuple[str, str, str], Mapping[str, object]]:
    """Return the latest metric for each ``(provider, model, prompt_id)`` tuple."""

    latest: Dict[Tuple[str, str, str], Tuple[datetime, Mapping[str, object]]] = {}
    for metric in metrics:
        provider = metric.get("provider")
        model = metric.get("model")
        prompt_id = metric.get("prompt_id")
        if provider is None or model is None or prompt_id is None:
            continue
        key = (str(provider), str(model), str(prompt_id))
        ts = parse_iso_ts(metric.get("ts"))
        existing = latest.get(key)
        if existing is None or ts >= existing[0]:
            latest[key] = (ts, metric)
    return {key: value for key, (_, value) in latest.items()}
