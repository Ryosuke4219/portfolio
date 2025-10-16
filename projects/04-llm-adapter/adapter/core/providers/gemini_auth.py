"""Gemini プロバイダ向け認証・例外正規化ユーティリティ。"""
from __future__ import annotations

from collections.abc import Mapping
import os
import textwrap
from typing import Any

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError

__all__ = [
    "resolve_api_key",
    "extract_status_code",
    "normalize_gemini_exception",
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
    sentinel = object()
    name_attr = getattr(candidate, "name", sentinel)
    if name_attr is sentinel:
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
        return TimeoutError("Gemini API び出しがタイムアウトしました")
    if name in {"Unavailable", "Internal", "InternalServerError", "ServiceUnavailable"} or (
        isinstance(status_code, int) and 500 <= status_code < 600
    ):
        return RetriableError("Gemini API が一時的に利用できません")
    return RetriableError("Gemini API 呼び出しに失敗しました")
