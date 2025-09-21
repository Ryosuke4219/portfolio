from dataclasses import dataclass
from typing import Optional, Dict, Any, Protocol

@dataclass
class ProviderRequest:
    prompt: str
    max_tokens: int = 256
    options: Optional[Dict[str, Any]] = None

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
    def name(self) -> str: ...
    def capabilities(self) -> set: ...
    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...
