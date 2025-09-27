"""Gemini provider integration for the minimal adapter."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from types import ModuleType
from typing import Any, Protocol, cast

try:  # pragma: no cover - import guard for offline test environments
    from google import genai as _genai_module
    from google.genai import types as _genai_types
except ModuleNotFoundError:  # pragma: no cover - fallback when SDK is unavailable
    genai: ModuleType | None = None
    gt: Any | None = None
else:
    genai = cast(ModuleType, _genai_module)
    gt = cast(Any, _genai_types)

if gt is None:  # pragma: no cover - stub for unit tests without the SDK

    class _GenerateContentConfig(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

        def to_dict(self) -> dict[str, Any]:
            return dict(self)

    class _TypesModule:
        GenerateContentConfig = _GenerateContentConfig

    gt = cast(Any, _TypesModule())

from ..errors import (
    AdapterError,
    AuthError,
    ConfigError,
    ProviderSkip,
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from ..provider_spi import (
    ProviderRequest,
    ProviderResponse,
    ProviderSPI,
    TokenUsage,
)

__all__ = ["GeminiProvider", "parse_gemini_messages"]


class _GeminiModelsAPI(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: Sequence[Mapping[str, Any]] | None,
        config: Mapping[str, Any] | None = None,
    ) -> Any:
        ...


class _GeminiResponsesAPI(Protocol):  # pragma: no cover - legacy fallback
    def generate(
        self,
        *,
        model: str,
        input: Sequence[Mapping[str, Any]] | None,
        config: Mapping[str, Any] | None = None,
    ) -> Any:
        ...


class _GeminiClient(Protocol):
    models: _GeminiModelsAPI | None
    responses: _GeminiResponsesAPI | None


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
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text

    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text:
        return text

    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, Iterable):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate_text = candidate.get("text")
                if isinstance(candidate_text, str) and candidate_text:
                    return candidate_text
            text_attr = getattr(candidate, "text", None)
            if isinstance(text_attr, str) and text_attr:
                return text_attr

    if hasattr(response, "to_dict"):
        payload = response.to_dict()
        if isinstance(payload, Mapping):
            text = payload.get("text")
            if isinstance(text, str) and text:
                return text
            text = payload.get("output_text")
            if isinstance(text, str) and text:
                return text

    return ""


def _coerce_finish_reason(response: Any) -> str | None:
    def _normalize(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "name"):
            candidate = value.name
            if isinstance(candidate, str):
                value = candidate
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return None

    candidates = getattr(response, "candidates", None)
    first_candidate: Any | None = None
    if isinstance(candidates, Iterable):
        for candidate in candidates:
            first_candidate = candidate
            break

    if first_candidate is None and hasattr(response, "to_dict"):
        payload = response.to_dict()
        if isinstance(payload, Mapping):
            candidates = payload.get("candidates")
            if isinstance(candidates, Iterable):
                for candidate in candidates:
                    first_candidate = candidate
                    break

    if first_candidate is None:
        return None

    if isinstance(first_candidate, Mapping):
        finish = _normalize(first_candidate.get("finish_reason"))
        if finish:
            return finish

    finish_attr = getattr(first_candidate, "finish_reason", None)
    return _normalize(finish_attr)


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

    if request.temperature is not None and "temperature" not in config:
        config["temperature"] = float(request.temperature)

    if request.top_p is not None and "top_p" not in config:
        config["top_p"] = float(request.top_p)

    if request.stop and "stop_sequences" not in config:
        config["stop_sequences"] = list(request.stop)

    return config or None


def _prepare_generation_config(
    base_config: Mapping[str, Any] | None,
    safety_settings: Sequence[Mapping[str, Any]] | None,
) -> tuple[Any | None, Mapping[str, Any] | None]:
    merged: dict[str, Any] = {}
    if base_config:
        merged.update(base_config)
    if safety_settings:
        merged["safety_settings"] = list(safety_settings)

    config_obj: Any | None = None
    if gt is not None:
        config_obj = gt.GenerateContentConfig(**merged)
    elif merged:
        config_obj = merged

    config_payload: Mapping[str, Any] | None = None
    if config_obj is not None:
        to_dict = getattr(config_obj, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            if isinstance(payload, Mapping) and payload:
                config_payload = payload
    if config_payload is None and merged:
        config_payload = merged

    return config_obj, config_payload


def _invoke_gemini(
    client: _GeminiClient,
    model: str,
    contents: Sequence[Mapping[str, Any]] | None,
    config: Mapping[str, Any] | None,
    safety_settings: Sequence[Mapping[str, Any]] | None,
) -> Any:
    config_obj, config_payload = _prepare_generation_config(config, safety_settings)
    models_api = getattr(client, "models", None)
    if models_api and hasattr(models_api, "generate_content"):
        try:
            model_kwargs: dict[str, Any] = {"model": model, "contents": contents}
            if config_obj is not None:
                model_kwargs["config"] = config_obj
            return models_api.generate_content(**model_kwargs)
        except TypeError as exc:  # pragma: no cover - legacy SDK fallback
            if "safety_settings" in str(exc):
                raise ConfigError(
                    "google-genai: use config=GenerateContentConfig(...)"
                ) from exc
            if "config" in str(exc) and config_payload is not None:
                return models_api.generate_content(model=model, contents=contents)
            raise

    responses_api = getattr(client, "responses", None)
    if responses_api and hasattr(responses_api, "generate"):
        try:
            response_kwargs: dict[str, Any] = {"model": model, "input": contents}
            if config_payload is not None:
                response_kwargs["config"] = config_payload
            return responses_api.generate(**response_kwargs)
        except TypeError as exc:  # pragma: no cover - legacy SDK fallback
            if "safety_settings" in str(exc):
                raise ConfigError(
                    "google-genai: use config=GenerateContentConfig(...)"
                ) from exc
            if "config" in str(exc):
                return responses_api.generate(model=model, input=contents)
            raise

    raise AttributeError("Gemini client does not provide a supported generate method")


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
    """Provider implementation backed by the Gemini SDK (models API)."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        client: _GeminiClient | None = None,
        generation_config: Mapping[str, Any] | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        # ``model`` は CLI/Factory で ``ProviderRequest`` に設定される想定だが、
        # 推奨デフォルトをメトリクスなどで参照できるよう記録しておく。
        self._model = model
        self._name = name or f"gemini:{model}"
        self._client: _GeminiClient | None = None
        self._client_module: Any | None = None
        if client is None:
            if genai is None:  # pragma: no cover - defensive branch
                raise ImportError(
                    "google-genai is not installed; provide a pre-configured client"
                )
            self._client_module = cast(Any, genai)
        else:
            self._client = cast(_GeminiClient, client)
        self._generation_config = dict(generation_config or {})
        self._safety_settings = list(safety_settings or [])

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, ConfigError):
            return exc

        if isinstance(exc, AdapterError) and not isinstance(exc, ProviderSkip):
            return exc

        def _has_timeout_marker(value: Any) -> bool:
            return isinstance(value, str) and "timeout" in value.lower()

        exc_type = type(exc)
        class_names = [
            getattr(exc_type, "__qualname__", ""),
            getattr(exc_type, "__name__", ""),
        ]
        module_names = [
            getattr(exc_type, "__module__", ""),
            getattr(exc, "__module__", ""),
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
            token = token.strip(" <>:,'\"")
            return token.upper()

        status_value: Any = None
        for attr_name in ("status", "code"):
            candidate = getattr(exc, attr_name, None)
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

        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
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

        config = _merge_generation_config(self._generation_config, request)
        safety_settings = _select_safety_settings(self._safety_settings, request)

        ts0 = time.time()
        try:
            client = self._resolve_client()
            model_name = request.model
            if not isinstance(model_name, str):
                raise ConfigError("GeminiProvider requires request.model to be set")
            model_name = model_name.strip()
            if not model_name:
                raise ConfigError("GeminiProvider requires request.model to be set")
            response = _invoke_gemini(client, model_name, messages, config, safety_settings)
        except ProviderSkip:
            raise
        except Exception as exc:  # pragma: no cover - translated in unit tests
            translated = self._translate_error(exc)
            raise translated from exc

        latency_ms = int((time.time() - ts0) * 1000)
        usage = _coerce_usage(response)
        text = _coerce_output_text(response)
        finish_reason = _coerce_finish_reason(response)

        return ProviderResponse(
            text=text,
            token_usage=usage,
            latency_ms=latency_ms,
            model=model_name,
            finish_reason=finish_reason,
            raw=response,
        )

    def _resolve_client(self) -> _GeminiClient:
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
        client = cast(_GeminiClient, module.Client(api_key=api_key_value))
        self._client = client
        return client
