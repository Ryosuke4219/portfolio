"""Client helpers for interacting with the Gemini SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any, Protocol, cast

from ..errors import ConfigError
from ..provider_spi import ProviderRequest

try:  # pragma: no cover - import guard for offline environments
    from google import genai as _genai_module
    from google.genai import types as _genai_types
except ModuleNotFoundError:  # pragma: no cover - SDK optional at runtime
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

__all__ = [
    "GeminiModelsAPI",
    "GeminiResponsesAPI",
    "GeminiClientProtocol",
    "genai",
    "invoke_gemini",
    "select_safety_settings",
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


class GeminiClientProtocol(Protocol):
    models: GeminiModelsAPI | None
    responses: GeminiResponsesAPI | None


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


def invoke_gemini(
    client: GeminiClientProtocol,
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


def select_safety_settings(
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
