"""Mock provider that can deterministically trigger failure modes."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import random
import time

from ..errors import AdapterError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from .base import BaseProvider

ErrorSpec = tuple[type[AdapterError], str]
_ERROR_BY_MARKER: dict[str, ErrorSpec] = {
    "[TIMEOUT]": (TimeoutError, "simulated timeout"),
    "[RATELIMIT]": (RateLimitError, "simulated rate limit"),
    "[INVALID_JSON]": (RetriableError, "simulated invalid JSON"),
}


class MockProvider(BaseProvider):
    """Very small provider implementation for exercising the adapter."""

    def __init__(
        self,
        name: str,
        base_latency_ms: int = 50,
        error_markers: Iterable[str] | None = None,
    ) -> None:
        super().__init__(name=name)
        self.base_latency_ms = base_latency_ms
        if error_markers is None:
            self._error_markers: set[str] = set(_ERROR_BY_MARKER)
        else:
            self._error_markers = {
                marker for marker in error_markers if marker in _ERROR_BY_MARKER
            }

    def _maybe_raise_error(self, text: str) -> None:
        for marker in self._error_markers:
            if marker in text:
                exc_cls, message = _ERROR_BY_MARKER[marker]
                raise exc_cls(message)

    def _merge_message_content(self, messages: Sequence[Mapping[str, object]]) -> str:
        parts: list[str] = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, Sequence):
                for entry in content:
                    if isinstance(entry, str):
                        parts.append(entry)
        return "\n".join(parts)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        text = request.prompt_text
        if not text:
            text = self._merge_message_content(request.chat_messages)
        self._maybe_raise_error(text)

        latency = self.base_latency_ms + int(random.random() * 20)
        time.sleep(latency / 1000.0)

        prompt_tokens = max(1, len(text) // 4)
        completion_tokens = 16

        provider_name = self.name()

        return ProviderResponse(
            text=f"echo({provider_name}): {text}",
            latency_ms=latency,
            token_usage=TokenUsage(prompt=prompt_tokens, completion=completion_tokens),
            model=request.model,
            finish_reason="stop",
            raw={
                "echo": text,
                "provider": provider_name,
            },
        )


__all__ = ["MockProvider"]
