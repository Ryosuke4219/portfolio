"""Gemini レスポンスの抽出・整形ユーティリティ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["extract_usage", "extract_output_text", "coerce_raw_output"]


def extract_usage(response: Any, prompt: str, output_text: str) -> tuple[int, int]:
    """Extract token usage information from Gemini responses."""

    prompt_tokens = 0
    output_tokens = 0
    usage = response.usage_metadata if hasattr(response, "usage_metadata") else None
    if usage is not None:
        if hasattr(usage, "input_tokens"):
            prompt_tokens = int(usage.input_tokens or 0)
        if hasattr(usage, "output_tokens"):
            output_tokens = int(usage.output_tokens or 0)
    else:
        payload = None
        if hasattr(response, "to_dict"):
            try:
                payload = response.to_dict()
            except Exception:  # pragma: no cover - defensive
                payload = None
        if isinstance(payload, Mapping):
            usage_dict = payload.get("usage_metadata")
            if isinstance(usage_dict, Mapping):
                prompt_tokens = int(usage_dict.get("input_tokens", 0) or 0)
                output_tokens = int(usage_dict.get("output_tokens", 0) or 0)
    if prompt_tokens <= 0:
        prompt_tokens = max(1, len(prompt.split()))
    if output_tokens <= 0:
        tokens = len(output_text.split())
        output_tokens = max(1, tokens) if tokens else 0
    return prompt_tokens, output_tokens


def extract_output_text(response: Any) -> str:
    """Extract best effort output text from Gemini responses."""

    if hasattr(response, "text"):
        text = response.text
        if isinstance(text, str) and text.strip():
            return text
    if hasattr(response, "output_text"):
        text = response.output_text
        if isinstance(text, str) and text.strip():
            return text
    candidates: Any
    if hasattr(response, "candidates"):
        candidates = response.candidates
    else:
        candidates = None
    if isinstance(candidates, Sequence):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate_text = candidate.get("text")
                if isinstance(candidate_text, str) and candidate_text.strip():
                    return candidate_text
            if hasattr(candidate, "text"):
                text_attr = candidate.text
                if isinstance(text_attr, str) and text_attr.strip():
                    return text_attr
    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        if isinstance(payload, Mapping):
            for key in ("text", "output_text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return ""


def coerce_raw_output(response: Any) -> Mapping[str, Any] | None:
    """Convert Gemini response objects into serializable dictionaries."""

    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        else:
            if isinstance(payload, Mapping):
                return dict(payload)
    if isinstance(response, Mapping):
        return dict(response)
    return {"repr": repr(response)}
