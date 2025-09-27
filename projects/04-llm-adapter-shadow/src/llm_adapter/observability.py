"""Event logging primitives for metrics emission."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, TextIO

PathLike = str | Path


def _ensure_dir(path: Path) -> None:
    parent = path.parent
    if parent != Path(""):
        parent.mkdir(parents=True, exist_ok=True)


class EventLogger(Protocol):
    """Protocol for structured event sinks."""

    def emit(self, event_type: str, path: PathLike, **fields: Any) -> None:
        """Persist a structured event."""
        ...


class JsonlLogger:
    """Append structured events to a JSONL file."""

    _LOCK = Lock()

    def emit(self, event_type: str, path: PathLike, **fields: Any) -> None:
        target = Path(path)
        _ensure_dir(target)

        record = dict(fields)
        record.setdefault("ts", int(time.time() * 1000))
        record["event"] = event_type

        with self._LOCK:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class StdLogger:
    """Write structured events to a text stream as JSONL."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream: TextIO = stream if stream is not None else sys.stdout

    def emit(self, event_type: str, path: PathLike, **fields: Any) -> None:  # pragma: no cover
        record = dict(fields)
        record.setdefault("ts", int(time.time() * 1000))
        record["event"] = event_type
        self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._stream.flush()


class CompositeLogger:
    """Broadcast events to multiple loggers."""

    def __init__(self, loggers: Sequence[EventLogger] | Iterable[EventLogger]) -> None:
        self._loggers: tuple[EventLogger, ...] = tuple(loggers)

    def emit(self, event_type: str, path: PathLike, **fields: Any) -> None:
        if not self._loggers:
            return

        payload = dict(fields)
        payload.setdefault("ts", int(time.time() * 1000))
        for logger in self._loggers:
            logger.emit(event_type, path, **payload)


DEFAULT_LOGGER = JsonlLogger()


__all__ = [
    "CompositeLogger",
    "DEFAULT_LOGGER",
    "EventLogger",
    "JsonlLogger",
    "StdLogger",
]
