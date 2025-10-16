"""OpenAI プロバイダ共通ユーティリティ。"""
from __future__ import annotations

from ..config import ProviderConfig
from .openai_client import OpenAIClientFactory
from .openai_extractors import coerce_raw_output, extract_text_from_response, extract_usage_tokens
from .openai_payloads import build_chat_messages, build_responses_input, build_system_user_contents

_API_ORDER = ("responses", "chat_completions", "completions")


def determine_modes(config: ProviderConfig, endpoint_mode: str | None) -> tuple[str, ...]:
    preferred = config.raw.get("api")
    modes: list[str] = []
    if isinstance(preferred, str) and preferred.strip():
        modes.append(preferred.strip().lower())
    if endpoint_mode:
        modes.append(endpoint_mode)
    modes.extend(_API_ORDER)
    seen: set[str] = set()
    ordered: list[str] = []
    for mode in modes:
        if mode not in _API_ORDER:
            continue
        if mode in seen:
            continue
        seen.add(mode)
        ordered.append(mode)
    return tuple(ordered)


__all__ = [
    "build_system_user_contents",
    "build_chat_messages",
    "build_responses_input",
    "extract_text_from_response",
    "extract_usage_tokens",
    "coerce_raw_output",
    "OpenAIClientFactory",
    "determine_modes",
]
