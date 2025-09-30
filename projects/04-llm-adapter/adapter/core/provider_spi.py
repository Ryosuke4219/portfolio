from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass
class ProviderRequest:
    model: str
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
        normalized = [
            {"role": str(entry.get("role", "")).strip() or "user", "content": entry.get("content")}
            for entry in (self.messages or [])
            if isinstance(entry, Mapping)
        ]
        if not normalized and self.prompt:
            normalized.append({"role": "user", "content": self.prompt})
        self.messages = normalized
        if not self.prompt and normalized:
            content = normalized[0].get("content")
            if isinstance(content, str):
                self.prompt = content
        if self.stop:
            self.stop = tuple(s for s in (str(x).strip() for x in self.stop) if s) or None


@dataclass
class TokenUsage:
    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass(init=False)
class ProviderResponse:
    text: str
    latency_ms: int
    model: str | None = None
    finish_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw: Any | None = None
    _token_usage: TokenUsage = field(init=False, repr=False, compare=False)

    def __init__(
        self,
        text: str,
        latency_ms: int,
        token_usage: TokenUsage | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        raw: Any | None = None,
    ) -> None:
        self.text = text
        self.latency_ms = latency_ms
        self.model = model
        self.finish_reason = finish_reason
        self.raw = raw
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        fallback = TokenUsage(prompt=int(tokens_in or 0), completion=int(tokens_out or 0))
        self.token_usage = token_usage or fallback

    @property
    def token_usage(self) -> TokenUsage:
        return self._token_usage

    @token_usage.setter
    def token_usage(self, value: TokenUsage) -> None:
        self._token_usage = value
        self.tokens_in = value.prompt
        self.tokens_out = value.completion


class ProviderSPI(Protocol):
    def name(self) -> str: ...
    def capabilities(self) -> set[str]: ...
    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...
