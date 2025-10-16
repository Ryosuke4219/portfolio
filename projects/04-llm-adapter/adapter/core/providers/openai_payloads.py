"""OpenAI ペイロード構築ユーティリティ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_system_user_contents(
    system_prompt: str | None, user_prompt: str
) -> list[Mapping[str, Any]]:
    contents: list[Mapping[str, Any]] = []
    if system_prompt:
        contents.append(
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}],
            }
        )
    contents.append({"role": "user", "content": [{"type": "text", "text": user_prompt}]})
    return contents


def build_chat_messages(system_prompt: str | None, user_prompt: str) -> list[Mapping[str, Any]]:
    messages: list[Mapping[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _as_responses_content(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        normalized: list[Mapping[str, Any]] = []
        for entry in value:
            if isinstance(entry, Mapping):
                normalized.append(dict(entry))
        if normalized:
            return normalized
    return [{"type": "text", "text": str(value)}]


def build_responses_input(
    system_prompt: str | None,
    messages: Sequence[Mapping[str, Any]] | None,
    user_prompt: str,
) -> list[Mapping[str, Any]]:
    contents: list[Mapping[str, Any]] = []
    if system_prompt:
        contents.append({"role": "system", "content": _as_responses_content(system_prompt)})
    if messages:
        for entry in messages:
            if not isinstance(entry, Mapping):
                continue
            role = str(entry.get("role", "")).strip() or "user"
            contents.append({"role": role, "content": _as_responses_content(entry.get("content"))})
    elif user_prompt:
        contents.append({"role": "user", "content": _as_responses_content(user_prompt)})
    return contents


__all__ = [
    "build_system_user_contents",
    "build_chat_messages",
    "build_responses_input",
]
