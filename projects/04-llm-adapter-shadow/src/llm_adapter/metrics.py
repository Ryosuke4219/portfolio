"""Lightweight JSONL metrics helpers."""

from __future__ import annotations

from typing import Any, Union

from .observability import DEFAULT_LOGGER, EventLogger

PathLike = Union[str, "Path"]

_DEFAULT_LOGGER: EventLogger = DEFAULT_LOGGER


def log_event(event_type: str, path: PathLike, **fields: Any) -> None:
    """Append a structured metrics record to ``path`` using the default logger."""

    _DEFAULT_LOGGER.emit(event_type, path, **fields)


__all__ = ["log_event"]
