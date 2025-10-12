"""Utility helpers shared by the Gemini provider implementation."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
import os
import textwrap
from typing import Any

from ..config import ProviderConfig
from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError

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


def resolve_api_key(env_name: str | None) -> str:
    """Return the Gemini API key resolved from the configured environment variable."""

    if not env_name:
        raise AuthError(
            textwrap.dedent(
                """
                Gemini プロバイダを利用するには auth_env に API キーの環境変数を指定してください
                """
            ).strip()
        )
    value = os.getenv(env_name)
    if not value:
        raise AuthError(f"Gemini API キーが環境変数 '{env_name}' に見つかりません")
    return value


_STATUS_NAME_TO_CODE = {
    "UNAUTHENTICATED": 401,
    "PERMISSION_DENIED": 403,
    "RESOURCE_EXHAUSTED": 429,
    "DEADLINE_EXCEEDED": 408,
    "UNAVAILABLE": 503,
}


def extract_status_code(exc: Exception) -> int | None:
    """Best-effort extraction of numeric status codes from Gemini SDK errors."""

    for attr in ("status_code", "code"):
        candidate = getattr(exc, attr, None)
        numeric = _coerce_status_code(candidate)
        if numeric is not None:
            return numeric
    return None


def _coerce_status_code(candidate: Any) -> int | None:
    if candidate is None:
        return None
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        try:
            return int(candidate)
        except ValueError:
            return _STATUS_NAME_TO_CODE.get(candidate)
    if isinstance(candidate, Mapping):
        mapping = dict(candidate)
        for key in ("status_code", "code", "value"):
            if key in mapping:
                nested = _coerce_status_code(mapping[key])
                if nested is not None:
                    return nested
        name_value = mapping.get("name")
        if isinstance(name_value, str):
            mapped = _STATUS_NAME_TO_CODE.get(name_value)
            if mapped is not None:
                return mapped
        return None
    for attr in ("value", "status_code", "code"):
        try:
            nested_candidate = getattr(candidate, attr)
        except AttributeError:
            continue
        nested = _coerce_status_code(nested_candidate)
        if nested is not None:
            return nested
    try:
        name_attr = getattr(candidate, "name")
    except AttributeError:
        return None
    if isinstance(name_attr, str):
        mapped = _STATUS_NAME_TO_CODE.get(name_attr)
        if mapped is not None:
            return mapped
        try:
            return int(name_attr)
        except ValueError:
            return None
    return None


def normalize_gemini_exception(exc: Exception) -> Exception:
    """Translate Gemini SDK exceptions into adapter error hierarchy."""

    status_code = extract_status_code(exc)
    name = exc.__class__.__name__
    if name in {"Unauthenticated", "PermissionDenied"} or (
        isinstance(status_code, int) and status_code in {401, 403}
    ):
        return AuthError("Gemini API 認証に失敗しました")
    if name in {"ResourceExhausted", "QuotaFailure", "BillingNotEnabled"} or (
        isinstance(status_code, int) and status_code == 429
    ):
        return RateLimitError("Gemini API のクォータ制限に達しました")
    if name in {"DeadlineExceeded", "Timeout"} or (
        isinstance(status_code, int) and status_code in {408, 504}
    ):
        return TimeoutError("Gemini API 呼び出しがタイムアウトしました")
    if name in {"Unavailable", "Internal", "InternalServerError", "ServiceUnavailable"} or (
        isinstance(status_code, int) and 500 <= status_code < 600
    ):
        return RetriableError("Gemini API が一時的に利用できません")
    return RetriableError("Gemini API 呼び出しに失敗しました")


def prepare_generation_config(config_obj: ProviderConfig) -> MutableMapping[str, Any]:
    """Prepare the generation config passed to the Gemini client."""

    config: MutableMapping[str, Any] = {}
    raw = config_obj.raw.get("generation_config")
    if isinstance(raw, Mapping):
        config.update(raw)
    if config_obj.temperature:
        config.setdefault("temperature", float(config_obj.temperature))
    if config_obj.top_p and config_obj.top_p < 1.0:
        config.setdefault("top_p", float(config_obj.top_p))
    if config_obj.max_tokens:
        config.setdefault("max_output_tokens", int(config_obj.max_tokens))
    return config


def prepare_safety_settings(
    config_obj: ProviderConfig,
) -> Sequence[Mapping[str, Any]] | None:
    """Return sanitized safety settings derived from provider config."""

    raw = config_obj.raw.get("safety_settings")
    if isinstance(raw, Sequence):
        candidates: list[Mapping[str, Any]] = []
        for item in raw:
            if isinstance(item, Mapping):
                candidates.append(dict(item))
        if candidates:
            return candidates
    return None


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


def extract_usage(response: Any, prompt: str, output_text: str) -> tuple[int, int]:
    """Extract token usage information from Gemini responses."""

    prompt_tokens = 0
    output_tokens = 0
    usage = response.usage_metadata if hasattr(response, "usage_metadata") else None
    if usage is not None:
        if hasattr(usage, "input_tokens"):
            prompt_tokens = int(usage.input_tokens or 0)
        if hasattr(usage, "output_tokens"):
            output_tokens = int(usage.output_tokens or 0)
    else:
        payload = None
        if hasattr(response, "to_dict"):
            try:
                payload = response.to_dict()
            except Exception:  # pragma: no cover - defensive
                payload = None
        if isinstance(payload, Mapping):
            usage_dict = payload.get("usage_metadata")
            if isinstance(usage_dict, Mapping):
                prompt_tokens = int(usage_dict.get("input_tokens", 0) or 0)
                output_tokens = int(usage_dict.get("output_tokens", 0) or 0)
    if prompt_tokens <= 0:
        prompt_tokens = max(1, len(prompt.split()))
    if output_tokens <= 0:
        tokens = len(output_text.split())
        output_tokens = max(1, tokens) if tokens else 0
    return prompt_tokens, output_tokens


def extract_output_text(response: Any) -> str:
    """Extract best effort output text from Gemini responses."""

    if hasattr(response, "text"):
        text = response.text
        if isinstance(text, str) and text.strip():
            return text
    if hasattr(response, "output_text"):
        text = response.output_text
        if isinstance(text, str) and text.strip():
            return text
    candidates: Any
    if hasattr(response, "candidates"):
        candidates = response.candidates
    else:
        candidates = None
    if isinstance(candidates, Sequence):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate_text = candidate.get("text")
                if isinstance(candidate_text, str) and candidate_text.strip():
                    return candidate_text
            if hasattr(candidate, "text"):
                text_attr = candidate.text
                if isinstance(text_attr, str) and text_attr.strip():
                    return text_attr
    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        if isinstance(payload, Mapping):
            for key in ("text", "output_text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return ""


def coerce_raw_output(response: Any) -> Mapping[str, Any] | None:
    """Convert Gemini response objects into serializable dictionaries."""

    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        else:
            if isinstance(payload, Mapping):
                return dict(payload)
    if isinstance(response, Mapping):
        return dict(response)
    return {"repr": repr(response)}

