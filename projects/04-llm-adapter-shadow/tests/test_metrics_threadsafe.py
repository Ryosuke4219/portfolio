from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from src.llm_adapter.metrics import log_event, PrometheusMetricsExporter


@pytest.mark.parametrize("thread_count,event_per_thread", [(8, 200)])
def test_log_event_threadsafe(tmp_path: Path, thread_count: int, event_per_thread: int) -> None:
    target = tmp_path / "events.jsonl"
    start_barrier = threading.Barrier(thread_count)

    def worker(thread_id: int) -> None:
        start_barrier.wait()
        for i in range(event_per_thread):
            log_event(
                "test",
                target,
                thread=thread_id,
                index=i,
            )

    threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected_records = thread_count * event_per_thread
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == expected_records

    for line in lines:
        record = json.loads(line)
        assert record["event"] == "test"
        assert "thread" in record
        assert "index" in record


def test_prometheus_exporter_accepts_numeric_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyCounter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.label_args: list[dict[str, str]] = []
            self.inc_values: list[float] = []

        def labels(self, **kwargs: str) -> DummyCounter:
            self.label_args.append(kwargs)
            return self

        def inc(self, amount: float = 1.0) -> None:
            self.inc_values.append(amount)

    class DummyHistogram(DummyCounter):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.observe_values: list[float] = []

        def observe(self, amount: float) -> None:
            self.observe_values.append(amount)

    dummy_module = SimpleNamespace(Counter=DummyCounter, Histogram=DummyHistogram)
    monkeypatch.setitem(sys.modules, "prometheus_client", dummy_module)

    exporter = PrometheusMetricsExporter(namespace="test")

    exporter.handle_event(
        "provider_call",
        {
            "provider": "stub",
            "status": "ok",
            "shadow_used": True,
            "latency_ms": 10,
            "tokens_in": 5,
            "tokens_out": 8,
        },
    )
    exporter.handle_event(
        "provider_call",
        {
            "provider": "stub",
            "status": "ok",
            "shadow_used": False,
            "latency_ms": 12.5,
            "tokens_in": 7.5,
            "tokens_out": 9.5,
        },
    )
    exporter.handle_event(
        "run_metric",
        {"provider": "stub", "status": "success", "latency_ms": 3},
    )
    exporter.handle_event(
        "run_metric",
        {"provider": "stub", "status": "success", "latency_ms": 4.5},
    )

    assert exporter._provider_tokens_in.inc_values == [5.0, 7.5]
    assert exporter._provider_tokens_out.inc_values == [8.0, 9.5]
    assert exporter._provider_call_latency_ms.observe_values == [10.0, 12.5]
    assert exporter._run_latency_ms.observe_values == [3.0, 4.5]
