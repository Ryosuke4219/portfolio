"""Utility helpers shared across the adapter."""

import hashlib
import time
from collections.abc import Mapping, Sequence
from typing import Any


def ensure_str_list(value: Any) -> list[str]:
    """Return a list of non-empty strings extracted from ``value``."""

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    parts: list[str] = []
    if isinstance(value, Sequence):
        for entry in value:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    parts.append(text)
    return parts


def normalize_message(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Normalize a chat message mapping into a canonical structure."""

    role = str(entry.get("role", "user")).strip() or "user"
    content = entry.get("content")
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        return {"role": role, "content": text}
    if isinstance(content, Sequence) and not isinstance(content, bytes | bytearray):
        parts = [part.strip() for part in content if isinstance(part, str) and part.strip()]
        if not parts:
            return None
        return {"role": role, "content": parts}
    if content is None:
        return None
    return {"role": role, "content": content}


def extract_prompt_from_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    """Find the most recent user-provided text snippet from ``messages``."""

    for message in reversed(messages):
        role = str(message.get("role", "")).lower()
        if role == "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, Sequence) and not isinstance(content, bytes | bytearray):
            for part in content:
                if isinstance(part, str) and part.strip():
                    return part.strip()
    return ""


def content_hash(
    provider: str,
    prompt: str,
    options: dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> str:
    """Return a deterministic hash for caching provider requests."""

    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(prompt.encode())
    h.update(repr(max_tokens).encode())
    if options:
        h.update(repr(sorted(options.items())).encode())
    return h.hexdigest()[:16]


def elapsed_ms(start_ts: float, *, now: float | None = None) -> int:
    """Return elapsed time in milliseconds since ``start_ts``."""

    current = time.time() if now is None else now
    return max(0, int((current - start_ts) * 1000))


def provider_model_name(provider: Any) -> str | None:
    """Extract a provider's configured model name when available."""

    for attr in ("model", "_model"):
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def safe_estimate_cost(provider: Any, tokens_in: int, tokens_out: int) -> float:
    """Safely execute ``provider.estimate_cost`` if it exists."""

    estimator = getattr(provider, "estimate_cost", None)
    if callable(estimator):
        try:
            return float(estimator(tokens_in, tokens_out))
        except Exception:  # pragma: no cover - defensive guard
            return 0.0
    return 0.0


__all__ = [
    "content_hash",
    "elapsed_ms",
    "ensure_str_list",
    "provider_model_name",
    "safe_estimate_cost",
    "normalize_message",
    "extract_prompt_from_messages",
]
