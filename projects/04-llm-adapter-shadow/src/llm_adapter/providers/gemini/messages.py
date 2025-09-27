"""Helpers for parsing Gemini message payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = ["parse_gemini_messages"]


def parse_gemini_messages(messages: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    """Convert chat-style messages into Gemini "Content" entries."""

    if not messages:
        return []

    converted: list[Mapping[str, Any]] = []
    for entry in messages:
        if not isinstance(entry, Mapping):
            continue
        role = str(entry.get("role", "user")).strip() or "user"
        raw_parts: Any = entry.get("content")
        parts_list: list[Mapping[str, str]] = []

        if isinstance(raw_parts, str):
            text_value = raw_parts.strip()
            if text_value:
                parts_list.append({"text": text_value})
        elif isinstance(raw_parts, Iterable):
            for part in raw_parts:
                if isinstance(part, str) and part.strip():
                    parts_list.append({"text": part.strip()})

        if parts_list:
            converted.append({"role": role, "parts": parts_list})

    return converted
