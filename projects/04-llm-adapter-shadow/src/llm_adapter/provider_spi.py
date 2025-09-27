from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from .utils import ensure_str_list
from .utils import extract_prompt_from_messages as _extract_prompt_from_messages
from .utils import normalize_message as _normalize_message

normalize_message = _normalize_message
extract_prompt_from_messages = _extract_prompt_from_messages


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


class AsyncProviderSPI(Protocol):
    def name(self) -> str: ...
    def capabilities(self) -> set[str]: ...
    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse: ...


class _AsyncProviderAdapter(AsyncProviderSPI):
    def __init__(
        self,
        provider: ProviderSPI | AsyncProviderSPI,
        *,
        async_invoke: Callable[[ProviderRequest], Awaitable[ProviderResponse]] | None = None,
    ) -> None:
        self._provider = provider
        self._async_invoke = async_invoke

    def name(self) -> str:
        return self._provider.name()

    def capabilities(self) -> set[str]:
        return self._provider.capabilities()

    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
        if self._async_invoke is not None:
            return await self._async_invoke(request)
        invoke = getattr(self._provider, "invoke", None)
        if not callable(invoke):
            raise TypeError("Provider does not expose a synchronous invoke() method")
        return await asyncio.to_thread(invoke, request)


def ensure_async_provider(provider: ProviderSPI | AsyncProviderSPI) -> AsyncProviderSPI:
    invoke_async = getattr(provider, "invoke_async", None)
    if callable(invoke_async):
        if inspect.iscoroutinefunction(invoke_async):
            return cast(AsyncProviderSPI, provider)

        async def _invoke(request: ProviderRequest) -> ProviderResponse:
            result = invoke_async(request)
            if inspect.isawaitable(result):
                return await cast(Awaitable[ProviderResponse], result)
            return cast(ProviderResponse, result)

        return _AsyncProviderAdapter(provider, async_invoke=_invoke)

    return _AsyncProviderAdapter(provider)


__all__ = [
    "ProviderSPI",
    "AsyncProviderSPI",
    "ProviderRequest",
    "ProviderResponse",
    "TokenUsage",
    "ensure_async_provider",
]
