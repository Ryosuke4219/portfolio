"""OpenRouter HTTP provider."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from typing import Any

from ..errors import AuthError, RateLimitError, RetriableError
from ..provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from ._requests_compat import SessionProtocol, create_session
from .base import BaseProvider

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
__all__ = ["OpenRouterProvider"]


def _token_usage(data: Mapping[str, Any]) -> TokenUsage:
    usage = data.get("usage")
    if not isinstance(usage, Mapping):
        return TokenUsage()
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    if not completion and usage.get("total_tokens") and prompt:
        completion = int(usage.get("total_tokens") or 0) - prompt
    return TokenUsage(prompt=prompt, completion=max(completion, 0))


class OpenRouterProvider(BaseProvider):
    """Minimal OpenRouter provider covering chat/completions."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        referer: str | None = None,
        title: str | None = None,
        session: SessionProtocol | None = None,
    ) -> None:
        provider_name = name or f"openrouter:{model}"
        super().__init__(name=provider_name, model=model)
        key = api_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
        self._api_key = key
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._referer = referer or os.environ.get("OPENROUTER_REFERER")
        self._title = title or os.environ.get("OPENROUTER_APP_TITLE")
        self._session = session or create_session()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if not self._api_key:
            raise AuthError("OpenRouter API key is required")

        stream = False
        if isinstance(request.options, Mapping):
            stream = bool(request.options.get("stream"))

        router_meta = {}
        if isinstance(request.metadata, Mapping):
            router_meta = request.metadata.get("router", {}) if isinstance(
                request.metadata.get("router"), Mapping
            ) else {}

        messages = request.chat_messages or [
            {"role": "user", "content": request.prompt_text}
        ]
        primary_model = request.model.split(",", 1)[0].strip()

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        if self._title:
            headers["X-Title"] = self._title
        if "," in request.model:
            headers["X-Router-Model"] = request.model
        provider_hint = router_meta.get("provider") if isinstance(router_meta, Mapping) else None
        if provider_hint:
            headers["X-Router-Provider"] = str(provider_hint)

        payload: dict[str, Any] = {"model": primary_model or self.model or "", "messages": messages}
        if request.max_tokens is not None:
            payload["max_tokens"] = int(request.max_tokens)
        if request.temperature is not None:
            payload["temperature"] = float(request.temperature)
        if request.top_p is not None:
            payload["top_p"] = float(request.top_p)
        if request.stop:
            payload["stop"] = list(request.stop)
        if stream:
            payload["stream"] = True

        timeout = request.timeout_s if request.timeout_s is not None else None
        url = f"{self._base_url}/chat/completions"
        start = time.perf_counter()
        with self._session.post(
            url,
            json=payload,
            headers=headers,
            stream=stream,
            timeout=timeout,
        ) as response:
            latency_ms = int((time.perf_counter() - start) * 1000)
            if response.status_code == 429:
                raise RateLimitError("openrouter: rate limited")
            if response.status_code >= 500:
                raise RetriableError(f"openrouter: server error {response.status_code}")
            if response.status_code >= 400:
                raise RetriableError(f"openrouter: http {response.status_code}")

            if stream:
                text_parts: list[str] = []
                finish_reason: str | None = None
                raw_chunks: list[Any] = []
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    decoded = raw_line.decode("utf-8")
                    if not decoded.startswith("data:"):
                        continue
                    payload_text = decoded.split("data:", 1)[1].strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    raw_chunks.append(chunk_data)
                    choice = chunk_data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    piece = delta.get("content")
                    if piece:
                        text_parts.append(str(piece))
                    finish_reason = choice.get("finish_reason") or finish_reason
                text = "".join(text_parts)
                token_usage = TokenUsage()
                raw: dict[str, Any] = {"chunks": raw_chunks}
            else:
                data = response.json()
                choices = data.get("choices", [{}])
                choice = choices[0] if choices else {}
                text = (
                    choice.get("message", {}).get("content")
                    or choice.get("text")
                    or ""
                )
                finish_reason = choice.get("finish_reason")
                token_usage = _token_usage(data)
                raw = data

        router_headers = {
            "id": response.headers.get("x-router"),
            "model": response.headers.get("x-router-model"),
            "provider": response.headers.get("x-router-provider"),
        }
        raw.setdefault("router", router_headers)
        return ProviderResponse(
            text=text,
            latency_ms=latency_ms,
            token_usage=token_usage,
            model=router_headers.get("model") or primary_model,
            finish_reason=finish_reason,
            raw=raw,
        )
