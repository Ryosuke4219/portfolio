from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .utils import (
    ensure_str_list,
    extract_prompt_from_messages,
    normalize_message,
)


@dataclass
class ProviderRequest:
    model: str = field(default="")
    prompt: str = ""
    messages: Sequence[Mapping[str, Any]] | None = None
    max_tokens: int | None = 256
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] | None = None
    timeout_s: float | None = 30
    metadata: Mapping[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        model = (self.model or "").strip()
        if not model:
            raise ValueError("ProviderRequest.model must be a non-empty string")
        self.model = model

        self.prompt = (self.prompt or "").strip()

        if self.options is None:
            self.options = {}

        normalized_messages: list[Mapping[str, Any]] = []
        if self.messages:
            for entry in self.messages:
                if isinstance(entry, Mapping):
                    normalized = normalize_message(entry)
                    if normalized:
                        normalized_messages.append(normalized)

        if not normalized_messages and self.prompt:
            normalized_messages.append({"role": "user", "content": self.prompt})

        self.messages = normalized_messages

        if not self.prompt and normalized_messages:
            self.prompt = extract_prompt_from_messages(normalized_messages)

        if self.stop is not None:
            stop_list = ensure_str_list(self.stop)
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
