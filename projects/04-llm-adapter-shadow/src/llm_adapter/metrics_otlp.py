from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
ScopeAttrs = list[dict[str, Any]]
def _timestamp_ns(value: Any) -> str:
    return str(int(float(value) * 1_000_000)) if isinstance(value, (int, float)) else "0"


def _encode_attrs(values: Mapping[str, Any]) -> ScopeAttrs:
    attrs: ScopeAttrs = []
    for key, raw in values.items():
        if raw is None:
            continue
        if isinstance(raw, bool):
            value: dict[str, Any] = {"boolValue": raw}
        elif isinstance(raw, int) and not isinstance(raw, bool):
            value = {"intValue": str(raw)}
        elif isinstance(raw, float):
            value = {"doubleValue": raw}
        else:
            value = {"stringValue": str(raw)}
        attrs.append({"key": str(key), "value": value})
    return attrs
def _gauge(name: str, timestamp: str, value: float, attrs: ScopeAttrs) -> dict[str, Any]:
    return {
        "name": name,
        "gauge": {"dataPoints": [{"timeUnixNano": timestamp, "asDouble": value, "attributes": attrs}]},
    }


class OtlpJsonExporter:
    _SCOPE = {"name": "llm-adapter.metrics"}
    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        *,
        service_name: str = "llm-adapter",
        resource_attributes: Mapping[str, Any] | None = None,
    ) -> None:
        attrs: dict[str, Any] = {"service.name": service_name}
        if resource_attributes:
            attrs.update(resource_attributes)
        self._emit = emit
        self._resource = {"attributes": _encode_attrs(attrs)}

    def handle_event(self, event_type: str, record: Mapping[str, Any]) -> None:
        if event_type not in {"provider_call", "run_metric"}:
            return
        timestamp = _timestamp_ns(record.get("ts"))
        attrs = _encode_attrs({k: v for k, v in record.items() if k not in {"ts", "event"}})
        log_record = {
            "timeUnixNano": timestamp,
            "observedTimeUnixNano": timestamp,
            "severityText": event_type,
            "body": {"stringValue": event_type},
            "attributes": attrs,
        }
        payload: dict[str, Any] = {
            "resourceLogs": [
                {
                    "resource": self._resource,
                    "scopeLogs": [{"scope": self._SCOPE, "logRecords": [log_record]}],
                }
            ]
        }
        metrics = self._metrics(event_type, record, timestamp, attrs)
        if metrics:
            payload["resourceMetrics"] = [
                {
                    "resource": self._resource,
                    "scopeMetrics": [{"scope": self._SCOPE, "metrics": metrics}],
                }
            ]
        self._emit(payload)

    def _metrics(
        self,
        event_type: str,
        record: Mapping[str, Any],
        timestamp: str,
        attrs: ScopeAttrs,
    ) -> list[dict[str, Any]]:
        numeric_fields = {
            "provider_call": ("latency_ms", "tokens_in", "tokens_out"),
            "run_metric": ("latency_ms", "tokens_in", "tokens_out", "cost_usd"),
        }
        fields = numeric_fields.get(event_type)
        if fields is None:
            return []
        metrics = [_gauge(f"llm_adapter.{event_type}.count", timestamp, 1.0, attrs)]
        prefix = f"llm_adapter.{event_type}."
        for field in fields:
            value = record.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics.append(_gauge(prefix + field, timestamp, float(value), attrs))
        return metrics
