from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    parts: list[str] = []
    if isinstance(value, Sequence):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                parts.append(entry.strip())
    return parts


def _normalize_message(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
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


def _extract_prompt_from_messages(messages: Sequence[Mapping[str, Any]]) -> str:
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


@dataclass
class ProviderRequest:
    model: str
    prompt: str = ""
    messages: Sequence[Mapping[str, Any]] | None = None
    max_tokens: int | None = 256
    temperature: float | None = None
    top_p: float | None = None
    stop: Sequence[str] | None = None
    timeout_s: float | None = 30
    metadata: Mapping[str, Any] | None = None
    options: dict[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        model = (self.model or "").strip()
        if not model:
            raise ValueError("ProviderRequest.model must be a non-empty string")
        self.model = model

        self.prompt = (self.prompt or "").strip()

        normalized_messages: list[Mapping[str, Any]] = []
        if self.messages:
            for entry in self.messages:
                if isinstance(entry, Mapping):
                    normalized = _normalize_message(entry)
                    if normalized:
                        normalized_messages.append(normalized)

        if not normalized_messages and self.prompt:
            normalized_messages.append({"role": "user", "content": self.prompt})

        self.messages = normalized_messages

        if not self.prompt and normalized_messages:
            self.prompt = _extract_prompt_from_messages(normalized_messages)

        if self.stop is not None:
            stop_list = _ensure_list(self.stop)
            self.stop = tuple(stop_list) if stop_list else None

    @property
    def chat_messages(self) -> list[Mapping[str, Any]]:
        return list(self.messages or [])

    @property
    def prompt_text(self) -> str:
        return self.prompt


@dataclass
class TokenUsage:
    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass
class ProviderResponse:
    text: str
    latency_ms: int
    token_usage: TokenUsage | None = None
    model: str | None = None
    finish_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw: Any | None = None

    def __post_init__(self) -> None:
        prompt_tokens = int(self.tokens_in or 0)
        completion_tokens = int(self.tokens_out or 0)
        if self.token_usage is not None:
            prompt_tokens = self.token_usage.prompt
            completion_tokens = self.token_usage.completion
        else:
            self.token_usage = TokenUsage(
                prompt=prompt_tokens,
                completion=completion_tokens,
            )
        self.tokens_in = prompt_tokens
        self.tokens_out = completion_tokens

    # 互換エイリアス
    @property
    def output_text(self) -> str:
        return self.text

    @property
    def input_tokens(self) -> int:
        return self.tokens_in or 0

    @property
    def output_tokens(self) -> int:
        return self.tokens_out or 0


class ProviderSPI(Protocol):
    def name(self) -> str: ...
    def capabilities(self) -> set[str]: ...
    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...


__all__ = ["ProviderSPI", "ProviderRequest", "ProviderResponse", "TokenUsage"]
