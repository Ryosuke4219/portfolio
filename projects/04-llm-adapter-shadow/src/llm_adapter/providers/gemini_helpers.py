"""Helper utilities for Gemini provider message and config handling."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any

from ..provider_spi import ProviderRequest, TokenUsage

__all__ = [
    "parse_gemini_messages",
    "coerce_usage",
    "coerce_output_text",
    "coerce_finish_reason",
    "merge_generation_config",
]


def parse_gemini_messages(
    messages: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
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


def coerce_usage(value: Any) -> TokenUsage:
    """Extract token usage metadata from ``value``."""

    prompt_tokens = 0
    completion_tokens = 0

    if value is None:
        return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)

    if hasattr(value, "usage_metadata"):
        usage_obj = value.usage_metadata
        if hasattr(usage_obj, "input_tokens"):
            prompt_tokens = int(usage_obj.input_tokens or 0)
        if hasattr(usage_obj, "output_tokens"):
            completion_tokens = int(usage_obj.output_tokens or 0)
    else:
        if hasattr(value, "to_dict"):
            payload = value.to_dict()
        elif isinstance(value, Mapping):
            payload = value
        else:
            payload = {}
        usage_dict = payload.get("usage_metadata")
        if isinstance(usage_dict, Mapping):
            prompt_tokens = int(usage_dict.get("input_tokens", 0) or 0)
            completion_tokens = int(usage_dict.get("output_tokens", 0) or 0)

    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


def coerce_output_text(response: Any) -> str:
    if hasattr(response, "text"):
        text = response.text
        if isinstance(text, str) and text:
            return text

    if hasattr(response, "output_text"):
        text = response.output_text
        if isinstance(text, str) and text:
            return text

    candidates = response.candidates if hasattr(response, "candidates") else None
    if isinstance(candidates, Iterable):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate_text = candidate.get("text")
                if isinstance(candidate_text, str) and candidate_text:
                    return candidate_text
            if hasattr(candidate, "text"):
                text_attr = candidate.text
                if isinstance(text_attr, str) and text_attr:
                    return text_attr

    if hasattr(response, "to_dict"):
        payload = response.to_dict()
        if isinstance(payload, Mapping):
            text = payload.get("text")
            if isinstance(text, str) and text:
                return text
            text = payload.get("output_text")
            if isinstance(text, str) and text:
                return text

    return ""


def coerce_finish_reason(response: Any) -> str | None:
    def _normalize(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "name"):
            candidate = value.name
            if isinstance(candidate, str):
                value = candidate
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return None

    candidates = response.candidates if hasattr(response, "candidates") else None
    first_candidate: Any | None = None
    if isinstance(candidates, Iterable):
        for candidate in candidates:
            first_candidate = candidate
            break

    if first_candidate is None and hasattr(response, "to_dict"):
        payload = response.to_dict()
        if isinstance(payload, Mapping):
            candidates = payload.get("candidates")
            if isinstance(candidates, Iterable):
                for candidate in candidates:
                    first_candidate = candidate
                    break

    if first_candidate is None:
        return None

    if isinstance(first_candidate, Mapping):
        finish = _normalize(first_candidate.get("finish_reason"))
        if finish:
            return finish

    if hasattr(first_candidate, "finish_reason"):
        return _normalize(first_candidate.finish_reason)

    return None


def merge_generation_config(
    base_config: Mapping[str, Any] | None,
    request: ProviderRequest,
) -> MutableMapping[str, Any] | None:
    config: MutableMapping[str, Any] = {}
    if base_config:
        config.update(base_config)

    option_config = None
    if request.options and isinstance(request.options, Mapping):
        option_config = request.options.get("generation_config")
    if isinstance(option_config, Mapping):
        config.update(option_config)

    if request.max_tokens and "max_output_tokens" not in config:
        config["max_output_tokens"] = int(request.max_tokens)

    if request.temperature is not None and "temperature" not in config:
        config["temperature"] = float(request.temperature)

    if request.top_p is not None and "top_p" not in config:
        config["top_p"] = float(request.top_p)

    if request.stop and "stop_sequences" not in config:
        config["stop_sequences"] = list(request.stop)

    return config or None
