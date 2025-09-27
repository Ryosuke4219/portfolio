"""Runtime helpers for interacting with the Gemini SDK."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from ...errors import (
    AdapterError,
    AuthError,
    ConfigError,
    ProviderSkip,
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from ...provider_spi import ProviderRequest, TokenUsage
from .config import prepare_generation_config

__all__ = [
    "GeminiRuntime",
    "GeminiClient",
    "GeminiModelsAPI",
    "GeminiResponsesAPI",
    "coerce_finish_reason",
    "coerce_output_text",
    "coerce_usage",
]


class GeminiModelsAPI(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: Sequence[Mapping[str, Any]] | None,
        config: Mapping[str, Any] | None = None,
    ) -> Any:
        ...


class GeminiResponsesAPI(Protocol):  # pragma: no cover - legacy fallback
    def generate(
        self,
        *,
        model: str,
        input: Sequence[Mapping[str, Any]] | None,
        config: Mapping[str, Any] | None = None,
    ) -> Any:
        ...


class GeminiClient(Protocol):
    models: GeminiModelsAPI | None
    responses: GeminiResponsesAPI | None


class GeminiRuntime:
    """Encapsulates SDK interactions and error translation."""

    def select_safety_settings(
        self,
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

    def invoke(
        self,
        client: GeminiClient,
        model: str,
        contents: Sequence[Mapping[str, Any]] | None,
        config: Mapping[str, Any] | None,
        safety_settings: Sequence[Mapping[str, Any]] | None,
    ) -> Any:
        config_obj, config_payload = prepare_generation_config(config, safety_settings)
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

    def translate_error(self, exc: Exception) -> Exception:
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
            token = token.strip(" <>:, '\"")
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


def coerce_usage(value: Any) -> TokenUsage:
    """Extract token usage metadata from ``value``."""

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


def coerce_output_text(response: Any) -> str:
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


def coerce_finish_reason(response: Any) -> str | None:
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
