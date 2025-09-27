"""Utility helpers for hashing request payloads."""

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

Options = Mapping[str, Any] | Sequence[tuple[str, Any]]


def content_hash(
    provider: str,
    prompt: str,
    options: Options | None = None,
    max_tokens: int | None = None,
) -> str:
    h = sha256()
    h.update(provider.encode())
    h.update(prompt.encode())
    h.update(repr(max_tokens).encode())
    if options:
        if isinstance(options, Mapping):
            items = options.items()
        else:
            items = options
        h.update(repr(sorted(items)).encode())
    return h.hexdigest()[:16]
