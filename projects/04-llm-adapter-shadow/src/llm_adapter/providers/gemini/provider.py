"""Gemini provider implementation."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from typing import Any, cast

from ...errors import ConfigError, ProviderSkip
from ...provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from ._sdk import genai
from .config import merge_generation_config
from .messages import parse_gemini_messages
from .runtime import (
    GeminiClient,
    GeminiRuntime,
    coerce_finish_reason,
    coerce_output_text,
    coerce_usage,
)

__all__ = ["GeminiProvider"]


class GeminiProvider(ProviderSPI):
    """Provider implementation backed by the Gemini SDK (models API)."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        client: GeminiClient | None = None,
        generation_config: Mapping[str, Any] | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
        runtime: GeminiRuntime | None = None,
    ) -> None:
        self._model = model
        self._name = name or f"gemini:{model}"
        self._client: GeminiClient | None = None
        self._client_module: Any | None = None
        if client is None:
            if genai is None:  # pragma: no cover - defensive branch
                raise ImportError(
                    "google-genai is not installed; provide a pre-configured client"
                )
            self._client_module = cast(Any, genai)
        else:
            self._client = cast(GeminiClient, client)
        self._generation_config = dict(generation_config or {})
        self._safety_settings = list(safety_settings or [])
        self._runtime = runtime or GeminiRuntime()

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        messages = parse_gemini_messages(request.chat_messages)

        if not messages and request.options and isinstance(request.options, Mapping):
            messages = parse_gemini_messages(request.options.get("messages"))

        system_message = None
        containers: list[Mapping[str, Any]] = []
        if isinstance(request.metadata, Mapping):
            containers.append(request.metadata)
        if request.options and isinstance(request.options, Mapping):
            containers.append(request.options)
        for container in containers:
            candidate = container.get("system")
            if isinstance(candidate, str) and candidate.strip():
                system_message = candidate.strip()
                break

        if system_message:
            has_system = any(entry.get("role") == "system" for entry in messages)
            if has_system:
                messages = [entry for entry in messages if entry.get("role") != "system"]
            system_entry = {"role": "system", "parts": [{"text": system_message}]}
            messages.insert(0, system_entry)

        if not messages:
            messages = [{"role": "user", "parts": [{"text": request.prompt_text}]}]

        config = merge_generation_config(self._generation_config, request)
        safety_settings = self._runtime.select_safety_settings(
            self._safety_settings, request
        )

        ts0 = time.time()
        try:
            client = self._resolve_client()
            model_name = request.model
            if not isinstance(model_name, str):
                raise ConfigError("GeminiProvider requires request.model to be set")
            model_name = model_name.strip()
            if not model_name:
                raise ConfigError("GeminiProvider requires request.model to be set")
            response = self._runtime.invoke(
                client, model_name, messages, config, safety_settings
            )
        except ProviderSkip:
            raise
        except Exception as exc:  # pragma: no cover - translated in unit tests
            translated = self._runtime.translate_error(exc)
            raise translated from exc

        latency_ms = int((time.time() - ts0) * 1000)
        usage = coerce_usage(response)
        text = coerce_output_text(response)
        finish_reason = coerce_finish_reason(response)

        return ProviderResponse(
            text=text,
            token_usage=usage,
            latency_ms=latency_ms,
            model=model_name,
            finish_reason=finish_reason,
            raw=response,
        )

    def _resolve_client(self) -> GeminiClient:
        if self._client is not None:
            return self._client
        if self._client_module is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Gemini client factory is unavailable")

        api_key = os.getenv("GEMINI_API_KEY")
        if api_key is None:
            raise ProviderSkip("gemini: GEMINI_API_KEY not set", reason="missing_gemini_api_key")

        api_key_value = api_key.strip()
        if not api_key_value:
            raise ProviderSkip("gemini: GEMINI_API_KEY not set", reason="missing_gemini_api_key")

        module = cast(Any, self._client_module)
        client = cast(GeminiClient, module.Client(api_key=api_key_value))
        self._client = client
        return client
