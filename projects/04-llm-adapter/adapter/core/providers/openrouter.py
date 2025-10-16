"""OpenRouter provider implementation for adapter core."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import time
from typing import Any

from ..config import ProviderConfig
from ..errors import AuthError, ProviderSkip, RateLimitError, RetriableError, SkipReason, TimeoutError
from ..provider_spi import ProviderRequest
from . import BaseProvider, ProviderResponse
from ._requests_compat import create_session, requests_exceptions
from .openrouter_auth import INTERNAL_OPTION_KEYS, prepare_auth
from .openrouter_payload import (
    build_payload,
    coerce_finish_reason,
    coerce_text,
    coerce_usage,
    extract_option_api_key,
)
from .openrouter_stream import consume_stream

__all__ = ["OpenRouterProvider", "requests_exceptions"]


_INTERNAL_OPTION_KEYS = INTERNAL_OPTION_KEYS


def _extract_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _normalize_error(exc: Exception) -> Exception:
    if isinstance(exc, TimeoutError):  # pragma: no cover - defensive
        return exc
    if isinstance(exc, requests_exceptions.Timeout):
        return TimeoutError(str(exc))
    if isinstance(exc, requests_exceptions.ConnectionError):
        return RetriableError(str(exc))
    if isinstance(exc, requests_exceptions.HTTPError):
        code = _extract_status_code(exc)
        message = str(exc)
        if code == 429:
            return RateLimitError(message)
        if code in {408, 504}:
            return TimeoutError(message)
        if code in {401, 403}:
            return AuthError(message or "OpenRouter authentication failed")
        if code is not None and code >= 500:
            return RetriableError(message)
        return RetriableError(message)
    if isinstance(exc, requests_exceptions.RequestException):
        code = _extract_status_code(exc)
        message = str(exc)
        if code in {401, 403}:
            return AuthError(message or "OpenRouter authentication failed")
        return RetriableError(message)
    return exc


class OpenRouterProvider(BaseProvider):
    """Provider that proxies chat completions to OpenRouter."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        context = prepare_auth(config, session_factory=create_session)
        self._session = context.session
        self._api_key = context.api_key
        self._base_url = context.base_url
        self._default_timeout = context.default_timeout
        self._auth_env_name = context.auth_env_name
        self._configured_auth_env = context.configured_auth_env
        self._config_options = dict(context.config_options)

    def _build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        options = request.options or {}
        return build_payload(request, self._config_options, options if isinstance(options, Mapping) else None)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        options = request.options or {}
        option_api_key, sanitized_option_keys = extract_option_api_key(options if isinstance(options, Mapping) else None)

        if sanitized_option_keys:
            INTERNAL_OPTION_KEYS.update(sanitized_option_keys)

        api_key = option_api_key or self._api_key
        if not api_key:
            resolved_env = self._auth_env_name or "OPENROUTER_API_KEY"
            configured_env = self._configured_auth_env or resolved_env
            if configured_env and configured_env != resolved_env:
                message = f"openrouter: {configured_env} (resolved as {resolved_env}) not set"
            else:
                message = f"openrouter: {resolved_env} not set"
            raise ProviderSkip(
                message,
                reason=SkipReason.MISSING_OPENROUTER_API_KEY,
            )
        timeout = request.timeout_s if request.timeout_s is not None else self._default_timeout
        stream = False
        headers = getattr(self._session, "headers", None)
        if isinstance(headers, MutableMapping):
            headers.setdefault("Content-Type", "application/json")
            headers["Authorization"] = f"Bearer {api_key}"
        if isinstance(options, Mapping):
            stream = bool(options.get("stream"))
            for key in ("request_timeout_s", "REQUEST_TIMEOUT_S"):
                raw_timeout = options.get(key)
                if raw_timeout is not None:
                    try:
                        timeout = float(raw_timeout)
                    except (TypeError, ValueError):  # pragma: no cover - defensive
                        continue
                    break
        payload = self._build_payload(request)
        if stream:
            payload.setdefault("stream", True)
        url = f"{self._base_url}/chat/completions"
        ts0 = time.time()
        try:
            response = self._session.post(url, json=payload, stream=stream, timeout=timeout)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _normalize_error(exc) from exc

        try:
            if stream:
                response.raise_for_status()
                aggregated, final_payload, finish_reason = consume_stream(response)
            else:
                response.raise_for_status()
                data = response.json()
                aggregated = coerce_text(data)
                final_payload = data
                finish_reason = coerce_finish_reason(data)
        except Exception as exc:
            response.close()
            raise _normalize_error(exc) from exc
        response.close()
        latency_ms = int((time.time() - ts0) * 1000)
        usage_payload: Mapping[str, Any] | None = None
        if isinstance(final_payload, Mapping):
            candidate = final_payload.get("usage")
            if isinstance(candidate, Mapping):
                usage_payload = candidate
        usage = coerce_usage(usage_payload)
        model_name = None
        if isinstance(final_payload, Mapping):
            model_value = final_payload.get("model")
            if isinstance(model_value, str):
                model_name = model_value
        if not model_name:
            model_name = request.model
        return ProviderResponse(
            text=aggregated,
            latency_ms=latency_ms,
            token_usage=usage,
            model=model_name,
            finish_reason=finish_reason,
            raw=final_payload,
        )
