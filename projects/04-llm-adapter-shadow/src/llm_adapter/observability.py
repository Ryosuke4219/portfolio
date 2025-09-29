"""Shared observability primitives for the shadow adapter."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import sys
from threading import Lock
from typing import Any, Protocol, TextIO

PathLike = str | Path


class EventLogger(Protocol):
    """Protocol for structured event loggers."""

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        """Persist ``record`` for ``event_type``."""


class JsonlLogger:
    """Append structured events to a JSONL file with basic locking."""

    def __init__(self, path: PathLike) -> None:
        self._path = Path(path)
        self._lock = Lock()

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        payload = dict(record)
        payload.setdefault("event", event_type)

        target = self._path
        parent = target.parent
        if parent != Path(""):
            parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class StdLogger:
    """Emit structured events to a text stream as JSON."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._lock = Lock()

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        payload = dict(record)
        payload.setdefault("event", event_type)

        with self._lock:
            self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._stream.flush()


class CompositeLogger:
    """Fan out events to multiple loggers while isolating failures."""

    def __init__(self, loggers: Iterable[EventLogger] | None = None) -> None:
        self._loggers: list[EventLogger] = list(loggers or ())
        self._lock = Lock()

    def add(self, logger: EventLogger) -> None:
        with self._lock:
            self._loggers.append(logger)

    def clear(self) -> None:
        with self._lock:
            self._loggers.clear()

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        with self._lock:
            loggers = tuple(self._loggers)

        for logger in loggers:
            try:
                logger.emit(event_type, record)
            except Exception:  # pragma: no cover - logger isolation
                continue
