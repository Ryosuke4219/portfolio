from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ProviderRequest:
    prompt: str
    max_tokens: int = 256
    options: dict[str, Any] | None = None


@dataclass
class TokenUsage:
    prompt: int
    completion: int

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass
class ProviderResponse:
    text: str
    token_usage: TokenUsage
    latency_ms: int


class ProviderSPI(Protocol):
    def name(self) -> str:
        ...

    def capabilities(self) -> set[str]:
        ...

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        ...


__all__ = ["ProviderSPI", "ProviderRequest", "ProviderResponse", "TokenUsage"]
