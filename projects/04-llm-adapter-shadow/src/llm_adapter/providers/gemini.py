"""Gemini provider integration for the minimal adapter."""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any, Protocol, cast

try:  # pragma: no cover - import guard for offline test environments
    from google import genai
except ModuleNotFoundError:  # pragma: no cover - fallback when SDK is unavailable
    genai = None

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI, TokenUsage

__all__ = ["GeminiProvider", "parse_gemini_messages"]


class _GeminiResponsesAPI(Protocol):
    def generate(
        self,
        *,
        model: str,
        input: Sequence[Mapping[str, Any]] | None,
        config: Mapping[str, Any] | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
    ) -> Any:
        ...


class _GeminiClient(Protocol):
    responses: _GeminiResponsesAPI


def _coerce_usage(value: Any) -> TokenUsage:
    """Extract token usage metadata from ``value``.

    The Google SDK exposes ``usage_metadata`` both as attributes on the
    ``GenerateContentResponse`` object and within ``to_dict()`` payloads. The
    helper is defensive so that tests can supply light-weight fakes.
    """

    prompt_tokens = 0
    completion_tokens = 0

    if value is None:
        return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)

    usage_obj = getattr(value, "usage_metadata", None)
    if usage_obj is not None:
        prompt_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
    else:
        if hasattr(value, "to_dict"):
            payload = value.to_dict()
        elif isinstance(value, Mapping):
            payload = value
        else:
            payload = {}
        usage_dict = payload.get("usage_metadata")
        if isinstance(usage_dict, Mapping):
            prompt_tokens = int(usage_dict.get("input_tokens", 0) or 0)
            completion_tokens = int(usage_dict.get("output_tokens", 0) or 0)

    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


def _coerce_output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str):
        return text

    if hasattr(response, "to_dict"):
        payload = response.to_dict()
        if isinstance(payload, Mapping):
            text = payload.get("output_text")
            if isinstance(text, str):
                return text

    return ""


def parse_gemini_messages(messages: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    """Convert chat-style messages into Gemini "Content" entries.

    The adapter keeps the schema intentionally small: each message is expected
    to provide ``role`` and ``content``. ``content`` may be either a string or a
    list of strings. Invalid entries are skipped gracefully so that the caller
    does not have to perform extensive validation ahead of time.
    """

    if not messages:
        return []

    converted: list[Mapping[str, Any]] = []
    for entry in messages:
        if not isinstance(entry, Mapping):
            continue
        role = str(entry.get("role", "user")).strip() or "user"
        raw_parts: Any = entry.get("content")
        parts_list: list[Mapping[str, str]] = []

        if isinstance(raw_parts, str):
            text_value = raw_parts.strip()
            if text_value:
                parts_list.append({"text": text_value})
        elif isinstance(raw_parts, Iterable):
            for part in raw_parts:
                if isinstance(part, str) and part.strip():
                    parts_list.append({"text": part.strip()})

        if parts_list:
            converted.append({"role": role, "parts": parts_list})

    return converted


def _merge_generation_config(
    base_config: Mapping[str, Any] | None,
    request: ProviderRequest,
) -> MutableMapping[str, Any] | None:
    config: MutableMapping[str, Any] = {}
    if base_config:
        config.update(base_config)

    option_config = None
    if request.options and isinstance(request.options, Mapping):
        option_config = request.options.get("generation_config")
    if isinstance(option_config, Mapping):
        config.update(option_config)

    if request.max_tokens and "max_output_tokens" not in config:
        config["max_output_tokens"] = int(request.max_tokens)

    return config or None


def _select_safety_settings(
    base_settings: Sequence[Mapping[str, Any]] | None,
    request: ProviderRequest,
) -> Sequence[Mapping[str, Any]] | None:
    if request.options and isinstance(request.options, Mapping):
        overrides = request.options.get("safety_settings")
        if isinstance(overrides, Sequence):
            return list(overrides)
    if base_settings:
        return list(base_settings)
    return None


class GeminiProvider(ProviderSPI):
    """Provider implementation backed by the Gemini Responses API."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        client: _GeminiClient | None = None,
        generation_config: Mapping[str, Any] | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._model = model
        self._name = name or f"gemini:{model}"
        if client is None:
            if genai is None:  # pragma: no cover - defensive branch
                raise ImportError(
                    "google-genai is not installed; provide a pre-configured client"
                )
            client = genai.Client()
        self._client: _GeminiClient = cast(_GeminiClient, client)
        self._generation_config = dict(generation_config or {})
        self._safety_settings = list(safety_settings or [])

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def _translate_error(self, exc: Exception) -> Exception:
        status = getattr(exc, "status", "") or getattr(exc, "code", "")
        status_text = str(status).upper()

        if status_text in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
            return AuthError(str(exc))
        if status_text in {"RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"}:
            return RateLimitError(str(exc))
        if status_text in {"DEADLINE_EXCEEDED", "GATEWAY_TIMEOUT"}:
            return TimeoutError(str(exc))

        return RetriableError(str(exc))

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        messages = []
        if request.options and isinstance(request.options, Mapping):
            messages = parse_gemini_messages(request.options.get("messages"))
            system_message = request.options.get("system")
            if isinstance(system_message, str) and system_message.strip():
                system_content = system_message.strip()
                if messages:
                    messages.insert(0, {"role": "system", "parts": [{"text": system_content}]})
                else:
                    messages = [{"role": "system", "parts": [{"text": system_content}]}]

        if not messages:
            messages = [{"role": "user", "parts": [{"text": request.prompt}]}]

        config = _merge_generation_config(self._generation_config, request)
        safety_settings = _select_safety_settings(self._safety_settings, request)

        ts0 = time.time()
        try:
            response = self._client.responses.generate(
                model=self._model,
                input=messages,
                config=config,
                safety_settings=safety_settings,
            )
        except Exception as exc:  # pragma: no cover - translated in unit tests
            translated = self._translate_error(exc)
            raise translated from exc

        latency_ms = int((time.time() - ts0) * 1000)
        usage = _coerce_usage(response)
        text = _coerce_output_text(response)

        return ProviderResponse(text=text, token_usage=usage, latency_ms=latency_ms)
