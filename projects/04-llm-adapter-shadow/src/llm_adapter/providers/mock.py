"""Mock provider that can deterministically trigger failure modes."""

from __future__ import annotations

import random
import time
from collections.abc import Iterable

from ..errors import AdapterError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI, TokenUsage

ErrorSpec = tuple[type[AdapterError], str]
_ERROR_BY_MARKER: dict[str, ErrorSpec] = {
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
        error_markers: Iterable[str] | None = None,
    ) -> None:
        self._name = name
        self.base_latency_ms = base_latency_ms
        if error_markers is None:
            self._error_markers: set[str] = set(_ERROR_BY_MARKER)
        else:
            self._error_markers = {
                marker for marker in error_markers if marker in _ERROR_BY_MARKER
            }

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def _maybe_raise_error(self, text: str) -> None:
        for marker in self._error_markers:
            if marker in text:
                exc_cls, message = _ERROR_BY_MARKER[marker]
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
