"""Utility helpers for hashing request payloads and timing."""

import hashlib
import time
from typing import Any


def content_hash(
    provider: str,
    prompt: str,
    options: dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> str:
    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(prompt.encode())
    h.update(repr(max_tokens).encode())
    if options:
        h.update(repr(sorted(options.items())).encode())
    return h.hexdigest()[:16]


def elapsed_ms(start_ts: float, *, end_ts: float | None = None) -> int:
    """Return elapsed milliseconds between ``start_ts`` and now (clamped to >= 0)."""

    end = end_ts if end_ts is not None else time.time()
    return max(0, int((end - start_ts) * 1000))
