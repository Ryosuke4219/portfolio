"""Utility helpers for hashing request payloads and message normalization."""

from collections.abc import Mapping, Sequence
import hashlib
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


__all__ = [
    "content_hash",
    "ensure_str_list",
    "normalize_message",
    "extract_prompt_from_messages",
]
