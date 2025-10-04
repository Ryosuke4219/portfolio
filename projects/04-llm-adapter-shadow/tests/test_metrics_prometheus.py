"""Tests for Prometheus metrics exporter status normalization."""
from __future__ import annotations

import sys
import types
from typing import Any

from pytest import MonkeyPatch

from src.llm_adapter.metrics import PrometheusMetricsExporter


class _LabelStub:
    def __init__(self, metric: _MetricStub, labels: dict[str, Any]) -> None:
        self._metric = metric
        self._labels = labels

    def inc(self, value: float | int = 1) -> None:  # noqa: D401 - simple stub
        self._metric.inc_calls.append((self._labels, value))

    def observe(self, value: float) -> None:  # noqa: D401 - simple stub
        self._metric.observe_calls.append((self._labels, value))


class _MetricStub:
    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401 - simple stub
        self.args = args
        self.kwargs = kwargs
        self.label_calls: list[dict[str, Any]] = []
        self.inc_calls: list[tuple[dict[str, Any], float | int]] = []
        self.observe_calls: list[tuple[dict[str, Any], float]] = []

    def labels(self, **labels: Any) -> _LabelStub:
        self.label_calls.append(labels)
        return _LabelStub(self, labels)


def test_prometheus_metrics_normalizes_errored_status(monkeypatch: MonkeyPatch) -> None:
    stub_module = types.SimpleNamespace(Counter=_MetricStub, Histogram=_MetricStub)
    monkeypatch.setitem(sys.modules, "prometheus_client", stub_module)

    exporter = PrometheusMetricsExporter(namespace="test")

    exporter.handle_event(
        "provider_call",
        {
            "provider": "demo",
            "status": "errored",
            "shadow_used": True,
            "latency_ms": 12,
        },
    )

    exporter.handle_event(
        "run_metric",
        {
            "provider": "demo",
            "status": "errored",
            "latency_ms": 34,
        },
    )

    assert exporter._provider_call_total.label_calls[-1]["status"] == "error"
    assert exporter._provider_call_latency_ms.label_calls[-1]["status"] == "error"
    assert exporter._run_total.label_calls[-1]["status"] == "error"
    assert exporter._run_latency_ms.label_calls[-1]["status"] == "error"
