from __future__ import annotations

from typing import Any

import pytest

from llm_adapter.metrics_otlp import OtlpJsonExporter


def _collect(event: str, record: dict[str, Any]) -> dict[str, Any]:
    sink: list[dict[str, Any]] = []
    OtlpJsonExporter(sink.append, resource_attributes={"deployment.environment": "test"}).handle_event(event, record)
    assert sink
    return sink[-1]


def _attr(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(item["value"] for item in items if item["key"] == key)


def _metric(payload: dict[str, Any], name: str) -> dict[str, Any]:
    metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    return next(metric for metric in metrics if metric["name"] == name)


def test_otlp_payloads_cover_provider_and_run_metrics() -> None:
    provider_record: dict[str, Any] = {
        "ts": 1_700_000_000_000,
        "provider": "primary",
        "status": "success",
        "latency_ms": 42,
        "tokens_in": 10,
        "tokens_out": 20,
        "shadow_used": True,
    }
    payload = _collect("provider_call", provider_record)
    attrs = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
    assert _attr(attrs, "provider")["stringValue"] == "primary"
    assert _attr(attrs, "status")["stringValue"] == "success"
    latency = _metric(payload, "llm_adapter.provider_call.latency_ms")["gauge"]["dataPoints"][0]
    assert pytest.approx(latency["asDouble"], rel=1e-6) == 42.0

    run_record = {
        "ts": 1_700_000_000_500,
        "provider": "primary",
        "status": "success",
        "attempts": 2,
        "latency_ms": 123,
        "tokens_in": 50,
        "tokens_out": 60,
        "cost_usd": 0.25,
        "shadow_used": False,
    }
    payload = _collect("run_metric", run_record)
    attrs = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
    assert _attr(attrs, "attempts")["intValue"] == "2"
    assert _attr(attrs, "shadow_used")["boolValue"] is False
    cost = _metric(payload, "llm_adapter.run_metric.cost_usd")["gauge"]["dataPoints"][0]
    assert pytest.approx(cost["asDouble"], rel=1e-6) == 0.25


@pytest.mark.parametrize("event_type", ("provider_call", "run_metric"))
def test_status_values_are_normalized_for_errored_status(event_type: str) -> None:
    record: dict[str, Any] = {
        "ts": 1_700_000_001_000,
        "provider": "primary",
        "status": "errored",
        "latency_ms": 10,
        "tokens_in": 1,
        "tokens_out": 2,
        "shadow_used": False,
    }
    if event_type == "run_metric":
        record["cost_usd"] = 0.01

    payload = _collect(event_type, record)
    log_attrs = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
    assert _attr(log_attrs, "status")["stringValue"] == "error"

    metric = _metric(payload, f"llm_adapter.{event_type}.count")
    metric_attrs = metric["gauge"]["dataPoints"][0]["attributes"]
    assert _attr(metric_attrs, "status")["stringValue"] == "error"


@pytest.mark.parametrize("event_type", ("provider_call", "run_metric"))
@pytest.mark.parametrize("status", ("failed",))
def test_status_values_are_normalized_for_failed_status(
    event_type: str, status: str
) -> None:
    record: dict[str, Any] = {
        "ts": 1_700_000_002_000,
        "provider": "primary",
        "status": status,
        "latency_ms": 10,
        "tokens_in": 1,
        "tokens_out": 2,
        "shadow_used": False,
    }
    if event_type == "run_metric":
        record["cost_usd"] = 0.01

    payload = _collect(event_type, record)
    log_attrs = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
    assert _attr(log_attrs, "status")["stringValue"] == "error"

    metric = _metric(payload, f"llm_adapter.{event_type}.count")
    metric_attrs = metric["gauge"]["dataPoints"][0]["attributes"]
    assert _attr(metric_attrs, "status")["stringValue"] == "error"
