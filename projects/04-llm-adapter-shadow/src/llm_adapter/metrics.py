"""Lightweight JSONL metrics helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Union

PathLike = Union[str, "Path"]


_LOG_LOCK = Lock()


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

    record = {"ts": int(time.time() * 1000), "event": event_type}
    record.update(fields)

    with _LOG_LOCK:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
