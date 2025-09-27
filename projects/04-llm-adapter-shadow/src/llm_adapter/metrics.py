"""Lightweight JSONL metrics helpers with optional exporters."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Union

PathLike = Union[str, "Path"]


class MetricsExporter(Protocol):
    """Protocol for metrics exporters that consume structured events."""

    def handle_event(self, event_type: str, record: Mapping[str, Any]) -> None:
        """Process a structured metrics ``record`` for ``event_type``."""


class EventLogger:
    """Fan out structured events to zero or more exporters."""

    def __init__(self) -> None:
        self._exporters: list[MetricsExporter] = []
        self._lock = Lock()

    def register(self, exporter: MetricsExporter) -> None:
        """Attach ``exporter`` for subsequent events."""

        with self._lock:
            self._exporters.append(exporter)

    def clear(self) -> None:
        """Remove all exporters (primarily for tests)."""

        with self._lock:
            self._exporters.clear()

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        """Notify registered exporters of ``record``."""

        with self._lock:
            exporters = tuple(self._exporters)

        for exporter in exporters:
            try:
                exporter.handle_event(event_type, record)
            except Exception:  # pragma: no cover - exporter isolation
                continue


class PrometheusMetricsExporter:
    """Translate adapter events into Prometheus counters and histograms."""

    def __init__(self, namespace: str = "llm_adapter") -> None:
        try:
            from prometheus_client import Counter, Histogram
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "prometheus_client is required to use PrometheusMetricsExporter"
            ) from exc

        metric_prefix = f"{namespace}_shadow"

        self._provider_call_total = Counter(
            f"{metric_prefix}_provider_call_total",
            "Total provider call attempts.",
            ("provider", "status", "shadow_used"),
        )
        self._provider_call_latency_ms = Histogram(
            f"{metric_prefix}_provider_call_latency_ms",
            "Latency of provider calls (ms).",
            ("provider", "status"),
        )
        self._provider_tokens_in = Counter(
            f"{metric_prefix}_provider_tokens_in_total",
            "Total prompt tokens sent to providers.",
            ("provider",),
        )
        self._provider_tokens_out = Counter(
            f"{metric_prefix}_provider_tokens_out_total",
            "Total completion tokens received from providers.",
            ("provider",),
        )
        self._run_total = Counter(
            f"{metric_prefix}_run_total",
            "Total run outcomes.",
            ("provider", "status"),
        )
        self._run_latency_ms = Histogram(
            f"{metric_prefix}_run_latency_ms",
            "End-to-end latency for completed runs (ms).",
            ("status",),
        )

    def handle_event(self, event_type: str, record: Mapping[str, Any]) -> None:
        if event_type == "provider_call":
            provider = str(record.get("provider") or "unknown")
            status = str(record.get("status") or "unknown")
            shadow_used = "true" if record.get("shadow_used") else "false"
            self._provider_call_total.labels(
                provider=provider, status=status, shadow_used=shadow_used
            ).inc()

            latency_ms = record.get("latency_ms")
            if isinstance(latency_ms, (int, float)) and latency_ms >= 0:
                self._provider_call_latency_ms.labels(
                    provider=provider, status=status
                ).observe(float(latency_ms))

            tokens_in = record.get("tokens_in")
            if isinstance(tokens_in, (int, float)) and tokens_in >= 0:
                self._provider_tokens_in.labels(provider=provider).inc(float(tokens_in))

            tokens_out = record.get("tokens_out")
            if isinstance(tokens_out, (int, float)) and tokens_out >= 0:
                self._provider_tokens_out.labels(provider=provider).inc(
                    float(tokens_out)
                )

        elif event_type == "run_metric":
            provider = str(record.get("provider") or "none")
            status = str(record.get("status") or "unknown")
            self._run_total.labels(provider=provider, status=status).inc()

            latency_ms = record.get("latency_ms")
            if isinstance(latency_ms, (int, float)) and latency_ms >= 0:
                self._run_latency_ms.labels(status=status).observe(float(latency_ms))


_LOG_LOCK = Lock()
_EVENT_LOGGER = EventLogger()


def register_metrics_exporter(exporter: MetricsExporter) -> None:
    """Register an ``exporter`` to receive future structured events."""

    _EVENT_LOGGER.register(exporter)


def reset_metrics_exporters() -> None:
    """Remove all registered exporters."""

    _EVENT_LOGGER.clear()


def _ensure_dir(path: Path) -> None:
    """Create the parent directory for ``path`` if it is missing."""

    parent = path.parent
    if parent != Path(""):
        parent.mkdir(parents=True, exist_ok=True)


def log_event(event_type: str, path: PathLike, **fields: Any) -> None:
    """Append a structured metrics record to ``path``.

    The file is encoded as UTF-8 JSONL so that it can easily be tailed or
    ingested by lightweight tooling.
    """

    target = Path(path)
    _ensure_dir(target)

    record: dict[str, Any] = {"ts": int(time.time() * 1000), "event": event_type}
    record.update(fields)

    with _LOG_LOCK:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    _EVENT_LOGGER.emit(event_type, MappingProxyType(record))
