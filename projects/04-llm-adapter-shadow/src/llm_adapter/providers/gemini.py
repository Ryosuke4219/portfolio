"""Gemini provider integration for the minimal adapter."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import re
import time
from typing import Any, cast

from ..errors import (
    AdapterError,
    AuthError,
    ConfigError,
    ProviderSkip,
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from ..provider_spi import ProviderRequest, ProviderResponse
from .base import BaseProvider
from .gemini_client import GeminiClientProtocol, genai, invoke_gemini, select_safety_settings
from .gemini_helpers import (
    coerce_finish_reason,
    coerce_output_text,
    coerce_usage,
    merge_generation_config,
    parse_gemini_messages,
)

__all__ = ["GeminiProvider", "parse_gemini_messages"]


class GeminiProvider(BaseProvider):
    """Provider implementation backed by the Gemini SDK (models API)."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        client: GeminiClientProtocol | None = None,
        generation_config: Mapping[str, Any] | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        provider_name = name or f"gemini:{model}"
        super().__init__(name=provider_name, model=model)
        self._client: GeminiClientProtocol | None = None
        self._client_module: Any | None = None
        if client is None:
            if genai is None:  # pragma: no cover - defensive branch
                raise ImportError(
                    "google-genai is not installed; provide a pre-configured client"
                )
            self._client_module = cast(Any, genai)
        else:
            self._client = client
        self._generation_config = dict(generation_config or {})
        self._safety_settings = list(safety_settings or [])

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, ConfigError):
            return exc

        if isinstance(exc, AdapterError) and not isinstance(exc, ProviderSkip):
            return exc

        def _has_timeout_marker(value: Any) -> bool:
            return isinstance(value, str) and "timeout" in value.lower()

        def _read_attr(obj: Any, name: str) -> Any:
            if obj is None:
                return None
            try:
                return getattr(obj, name)
            except AttributeError:
                return None

        def _read_str_attr(obj: Any, name: str) -> str:
            value = _read_attr(obj, name)
            return value if isinstance(value, str) else ""

        exc_type = type(exc)
        class_names = [
            _read_str_attr(exc_type, attr) for attr in ("__qualname__", "__name__")
        ]
        module_names = [
            _read_str_attr(target, "__module__") for target in (exc_type, exc)
        ]
        if any(_has_timeout_marker(name) for name in class_names + module_names):
            return TimeoutError(str(exc))

        def _normalize_status(value: Any) -> str:
            if not value:
                return ""

            if hasattr(value, "name"):
                name = value.name
                if isinstance(name, str) and name.strip():
                    value = name

            if not isinstance(value, str):
                value = str(value)

            text = value.strip()
            if not text:
                return ""

            token = text.split()[0]
            if "." in token:
                token = token.split(".")[-1]
            token = re.sub(r"^[ <>:,\'\"]+|[ <>:,\'\"]+$", "", token)
            return token.upper()

        status_value: Any = None
        for attr_name in ("status", "code"):
            candidate = _read_attr(exc, attr_name)
            if candidate is None:
                continue
            if callable(candidate):
                original = candidate
                try:
                    candidate = candidate()
                except Exception:  # pragma: no cover - defensive fallback
                    candidate = original
            if candidate:
                status_value = candidate
                break
        status_text = _normalize_status(status_value)

        response = _read_attr(exc, "response")
        status_code = _read_attr(response, "status_code")
        try:
            http_status = int(status_code) if status_code is not None else None
        except (TypeError, ValueError):  # pragma: no cover - defensive fallback
            http_status = None

        message = str(exc)

        if status_text in {"UNAUTHENTICATED", "PERMISSION_DENIED"} or http_status in {401, 403}:
            return AuthError(message)
        if status_text in {"RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"} or http_status == 429:
            return RateLimitError(message)
        if status_text in {"DEADLINE_EXCEEDED", "GATEWAY_TIMEOUT"} or http_status in {408, 504}:
            return TimeoutError(message)

        return RetriableError(message)

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
        safety_settings = select_safety_settings(self._safety_settings, request)

        ts0 = time.time()
        try:
            client = self._resolve_client()
            model_name = request.model
            if not isinstance(model_name, str):
                raise ConfigError("GeminiProvider requires request.model to be set")
            model_name = model_name.strip()
            if not model_name:
                raise ConfigError("GeminiProvider requires request.model to be set")
            response = invoke_gemini(client, model_name, messages, config, safety_settings)
        except ProviderSkip:
            raise
        except Exception as exc:  # pragma: no cover - translated in unit tests
            translated = self._translate_error(exc)
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

    def _resolve_client(self) -> GeminiClientProtocol:
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
        client = cast(GeminiClientProtocol, module.Client(api_key=api_key_value))
        self._client = client
        return client
