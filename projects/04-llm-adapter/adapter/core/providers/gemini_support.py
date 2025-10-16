"""Utility helpers shared by the Gemini provider implementation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .gemini_auth import (
    extract_status_code,
    normalize_gemini_exception,
    resolve_api_key,
)
from .gemini_config import prepare_generation_config, prepare_safety_settings
from .gemini_response import coerce_raw_output, extract_output_text, extract_usage

__all__ = [
    "resolve_api_key",
    "extract_status_code",
    "normalize_gemini_exception",
    "prepare_generation_config",
    "prepare_safety_settings",
    "call_with_optional_safety",
    "invoke_gemini",
    "extract_usage",
    "extract_output_text",
    "coerce_raw_output",
]


def call_with_optional_safety(
    func: Any,
    *,
    model: str,
    config: Mapping[str, Any] | None,
    safety_settings: Sequence[Mapping[str, Any]] | None,
    payload_key: str,
    payload: Any,
) -> Any:
    """Invoke Gemini SDK call supporting optional safety settings argument."""

    kwargs: dict[str, Any] = {"model": model, payload_key: payload}
    if config:
        kwargs["config"] = config
    if safety_settings:
        kwargs["safety_settings"] = safety_settings
    try:
        return func(**kwargs)
    except TypeError as exc:  # pragma: no cover - 旧 SDK 互換
        if safety_settings and "safety_settings" in str(exc):
            kwargs.pop("safety_settings", None)
            return func(**kwargs)
        raise


def invoke_gemini(
    client: Any,
    model: str,
    contents: Sequence[Mapping[str, Any]] | None,
    config: Mapping[str, Any] | None,
    safety_settings: Sequence[Mapping[str, Any]] | None,
) -> Any:
    """Call the Gemini SDK using the available client APIs."""

    try:
        models_api = client.models
    except AttributeError:
        models_api = None
    if models_api is not None:
        try:
            func = models_api.generate_content
        except AttributeError:
            pass
        else:
            return call_with_optional_safety(
                func,
                model=model,
                config=config,
                safety_settings=safety_settings,
                payload_key="contents",
                payload=contents,
            )
    try:
        responses_api = client.responses
    except AttributeError:
        responses_api = None
    if responses_api is not None:
        try:
            func = responses_api.generate
        except AttributeError:
            pass
        else:
            return call_with_optional_safety(
                func,
                model=model,
                config=config,
                safety_settings=safety_settings,
                payload_key="input",
                payload=contents,
            )
    raise AttributeError("Gemini クライアントが対応する generate メソッドを提供していません")
