"""Streaming helpers for the OpenRouter provider."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from typing import Any

from .openrouter_payload import coerce_finish_reason, coerce_text

__all__ = ["consume_stream"]


def consume_stream(response: Any) -> tuple[str, Mapping[str, Any], str | None]:
    chunks: list[str] = []
    final_payload: Mapping[str, Any] = {}
    finish_reason: str | None = None
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        try:
            decoded = raw_line.decode("utf-8")
        except AttributeError:
            decoded = str(raw_line)
        decoded = decoded.strip()
        if not decoded:
            continue
        if decoded.startswith("data:"):
            decoded = decoded[len("data:") :].strip()
        if not decoded or decoded == "[DONE]":
            continue
        try:
            event = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        choices = event.get("choices")
        if isinstance(choices, Iterable):
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, Mapping):
                    content = delta.get("content")
                    if isinstance(content, str):
                        chunks.append(content)
                elif isinstance(delta, str):
                    chunks.append(delta)
                message = choice.get("message")
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        final_payload = event
                finish = choice.get("finish_reason")
                if isinstance(finish, str):
                    finish_reason = finish
        usage_payload = event.get("usage")
        if isinstance(usage_payload, Mapping):
            final_payload = event
    if not final_payload:
        text_value = "".join(chunks)
        final_payload = {
            "choices": [
                {"message": {"role": "assistant", "content": text_value}},
            ]
        }
    aggregated = "".join(chunks) or coerce_text(final_payload)
    if finish_reason is None:
        finish_reason = coerce_finish_reason(final_payload)
    return aggregated, final_payload, finish_reason
