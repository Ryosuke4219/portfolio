from __future__ import annotations

import json
from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any

from ..provider_spi import ProviderResponse


def _read_structured_payload(text: str, *, jsonl: bool = False) -> dict[str, Any] | None:
    if jsonl:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
            except JSONDecodeError as exc:  # pragma: no cover - invalid JSON handled by caller
                raise ValueError("failed to parse JSONL input") from exc
            if not isinstance(data, Mapping):
                raise ValueError("JSONL input must contain JSON objects")
            return dict(data)
        return None
    try:
        data = json.loads(text)
    except JSONDecodeError as exc:  # pragma: no cover - invalid JSON handled by caller
        raise ValueError("failed to parse JSON input") from exc
    if not isinstance(data, Mapping):
        raise ValueError("JSON input must be an object")
    return dict(data)


def _format_output(response: ProviderResponse, fmt: str) -> str:
    if fmt == "text":
        return response.text
    provider_name: str | None = None
    raw_payload = response.raw
    if isinstance(raw_payload, Mapping):
        provider_candidate = raw_payload.get("provider")
        if isinstance(provider_candidate, str) and provider_candidate.strip():
            provider_name = provider_candidate.strip()
    if not provider_name:
        provider_name = response.model or ""
    token_usage = response.token_usage
    payload: dict[str, Any] = {
        "status": "success",
        "text": response.text,
        "provider": provider_name,
        "model": response.model,
        "latency_ms": response.latency_ms,
        "token_usage": {
            "prompt": token_usage.prompt,
            "completion": token_usage.completion,
            "total": token_usage.total,
        },
    }
    if response.finish_reason is not None:
        payload["finish_reason"] = response.finish_reason
    if isinstance(raw_payload, Mapping):
        payload["raw"] = raw_payload
    return json.dumps(payload, ensure_ascii=False)


__all__ = ["_read_structured_payload", "_format_output"]
