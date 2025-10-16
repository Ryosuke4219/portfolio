"""Payload helpers for the OpenRouter provider."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..provider_spi import ProviderRequest, TokenUsage
from .openrouter_auth import INTERNAL_OPTION_KEYS, OPTION_CREDENTIAL_KEYS, normalize_option_credential

__all__ = [
    "build_payload",
    "coerce_finish_reason",
    "coerce_text",
    "coerce_usage",
    "extract_option_api_key",
]


def extract_option_api_key(options: Mapping[str, Any] | None) -> tuple[str, set[str]]:
    option_api_key = ""
    sanitized_option_keys: set[str] = set()
    if isinstance(options, Mapping):
        for key in OPTION_CREDENTIAL_KEYS:
            if key not in options:
                continue
            sanitized_option_keys.add(key)
            raw_value = options.get(key)
            credential = normalize_option_credential(raw_value)
            if credential and not option_api_key:
                option_api_key = credential
    return option_api_key, sanitized_option_keys


def build_payload(
    request: ProviderRequest,
    config_options: Mapping[str, Any] | None,
    request_options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    messages = [dict(message) for message in (request.messages or [])]
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = int(request.max_tokens)
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.stop is not None:
        payload["stop"] = list(request.stop)
    if isinstance(config_options, Mapping):
        for key, value in config_options.items():
            if key in INTERNAL_OPTION_KEYS:
                continue
            payload[key] = value
    if isinstance(request_options, Mapping):
        for key, value in request_options.items():
            if key in INTERNAL_OPTION_KEYS:
                continue
            payload[key] = value
    return payload


def coerce_text(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, Iterable):
        chunks: list[str] = []
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    chunks.append(content)
            delta = choice.get("delta")
            if isinstance(delta, Mapping):
                content = delta.get("content")
                if isinstance(content, str):
                    chunks.append(content)
            if isinstance(delta, str):
                chunks.append(delta)
            text_value = choice.get("text")
            if isinstance(text_value, str):
                chunks.append(text_value)
        if chunks:
            return "".join(chunks)
    return ""


def coerce_usage(payload: Mapping[str, Any] | None) -> TokenUsage:
    if not isinstance(payload, Mapping):
        return TokenUsage()
    prompt_tokens = payload.get("prompt_tokens") or 0
    completion_tokens = payload.get("completion_tokens") or 0
    try:
        prompt_value = int(prompt_tokens)
    except (TypeError, ValueError):
        prompt_value = 0
    try:
        completion_value = int(completion_tokens)
    except (TypeError, ValueError):
        completion_value = 0
    return TokenUsage(prompt=prompt_value, completion=completion_value)


def coerce_finish_reason(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    choices = payload.get("choices")
    if isinstance(choices, Iterable):
        for choice in choices:
            if isinstance(choice, Mapping):
                finish = choice.get("finish_reason")
                if isinstance(finish, str):
                    return finish
    finish = payload.get("finish_reason")
    if isinstance(finish, str):
        return finish
    return None
