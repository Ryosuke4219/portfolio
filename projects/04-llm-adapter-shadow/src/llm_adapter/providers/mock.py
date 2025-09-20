"""Mock provider that can deterministically trigger failure modes."""

from __future__ import annotations

import random
import time
from typing import Iterable, Optional, Set

from ..provider_spi import ProviderSPI, ProviderRequest, ProviderResponse, TokenUsage
from ..errors import TimeoutError, RateLimitError, RetriableError

_MARKER_TO_ERROR = {
    "[TIMEOUT]": (TimeoutError, "simulated timeout"),
    "[RATELIMIT]": (RateLimitError, "simulated rate limit"),
    "[INVALID_JSON]": (RetriableError, "simulated invalid JSON"),
}


class MockProvider(ProviderSPI):
    """Very small provider implementation for exercising the adapter."""

    def __init__(
        self,
        name: str,
        base_latency_ms: int = 50,
        error_markers: Optional[Iterable[str]] = None,
    ) -> None:
        self._name = name
        self.base_latency_ms = base_latency_ms
        if error_markers is None:
            self._error_markers: Set[str] = set(_MARKER_TO_ERROR)
        else:
            self._error_markers = {marker for marker in error_markers if marker in _MARKER_TO_ERROR}

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set:
        return {"chat"}

    def _maybe_raise_error(self, text: str) -> None:
        for marker in self._error_markers:
            if marker in text:
                exc_cls, message = _MARKER_TO_ERROR[marker]
                raise exc_cls(message)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        text = request.prompt
        self._maybe_raise_error(text)

        latency = self.base_latency_ms + int(random.random() * 20)
        time.sleep(latency / 1000.0)

        prompt_tokens = max(1, len(text) // 4)
        completion_tokens = 16

        return ProviderResponse(
            text=f"echo({self._name}): {text}",
            token_usage=TokenUsage(prompt=prompt_tokens, completion=completion_tokens),
            latency_ms=latency,
        )


__all__ = ["MockProvider"]
