"""Helpers for preparing Ollama request payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...errors import ConfigError
from ...provider_spi import ProviderRequest

PayloadDict = dict[str, Any]
TimeoutOverride = float | None

__all__ = ["prepare_chat_payload"]


def _coerce_content(entry: Mapping[str, Any]) -> str:
    content = entry.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        parts = [part for part in content if isinstance(part, str)]
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def prepare_chat_payload(
    request: ProviderRequest,
    *,
    model_name: str,
    stream: bool = False,
) -> tuple[PayloadDict, TimeoutOverride]:
    """Build the JSON payload for ``/api/chat`` requests."""
    messages_payload: list[dict[str, str]] = []
    for message in request.chat_messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role", "user")) or "user"
        text = _coerce_content(message).strip()
        if text:
            messages_payload.append({"role": role, "content": text})

    if not messages_payload and request.prompt_text:
        messages_payload.append({"role": "user", "content": request.prompt_text})

    payload: PayloadDict = {
        "model": model_name,
        "messages": messages_payload,
        "stream": stream,
    }

    options_payload: dict[str, Any] = {}
    if request.max_tokens is not None:
        options_payload["num_predict"] = int(request.max_tokens)
    if request.temperature is not None:
        options_payload["temperature"] = float(request.temperature)
    if request.top_p is not None:
        options_payload["top_p"] = float(request.top_p)
    if request.stop:
        options_payload["stop"] = list(request.stop)

    timeout_override: TimeoutOverride = None
    if request.timeout_s is not None:
        timeout_override = float(request.timeout_s)

    if request.options and isinstance(request.options, Mapping):
        opt_items = dict(request.options.items())

        for key in ("request_timeout_s", "REQUEST_TIMEOUT_S"):
            if key in opt_items:
                raw_timeout = opt_items.pop(key)
                if raw_timeout is not None and timeout_override is None:
                    try:
                        timeout_override = float(raw_timeout)
                    except (TypeError, ValueError) as exc:
                        raise ConfigError("request_timeout_s must be a number") from exc
                break

        for key in ("model", "messages", "prompt"):
            opt_items.pop(key, None)

        nested_opts = opt_items.pop("options", None)
        if isinstance(nested_opts, Mapping):
            options_payload.update(dict(nested_opts))

        for key, value in opt_items.items():
            payload[key] = value

    if options_payload:
        payload["options"] = {**options_payload, **payload.get("options", {})}

    return payload, timeout_override
