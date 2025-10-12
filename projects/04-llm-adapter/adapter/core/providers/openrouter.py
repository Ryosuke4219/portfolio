"""OpenRouter provider implementation for adapter core."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
import json
import os
import time
from typing import Any, cast

from ..config import ProviderConfig
from ..errors import AuthError, ProviderSkip, RateLimitError, RetriableError, SkipReason, TimeoutError
from ..provider_spi import ProviderRequest, TokenUsage
from . import BaseProvider, ProviderResponse
from ._requests_compat import create_session, requests_exceptions, SessionProtocol

__all__ = ["OpenRouterProvider", "requests_exceptions"]


_INTERNAL_OPTION_KEYS = {"stream", "request_timeout_s", "REQUEST_TIMEOUT_S"}


_LITERAL_ENV_VALUE_PREFIXES = ("file:", "mailto:")


def _coerce_text(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, Iterable):
        chunks: list[str] = []
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    chunks.append(content)
            delta = choice.get("delta")
            if isinstance(delta, Mapping):
                content = delta.get("content")
                if isinstance(content, str):
                    chunks.append(content)
            if isinstance(delta, str):
                chunks.append(delta)
            text_value = choice.get("text")
            if isinstance(text_value, str):
                chunks.append(text_value)
        if chunks:
            return "".join(chunks)
    return ""


def _coerce_usage(payload: Mapping[str, Any] | None) -> TokenUsage:
    if not isinstance(payload, Mapping):
        return TokenUsage()
    prompt_tokens = payload.get("prompt_tokens") or 0
    completion_tokens = payload.get("completion_tokens") or 0
    try:
        prompt_value = int(prompt_tokens)
    except (TypeError, ValueError):
        prompt_value = 0
    try:
        completion_value = int(completion_tokens)
    except (TypeError, ValueError):
        completion_value = 0
    return TokenUsage(prompt=prompt_value, completion=completion_value)


def _coerce_finish_reason(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    choices = payload.get("choices")
    if isinstance(choices, Iterable):
        for choice in choices:
            if isinstance(choice, Mapping):
                finish = choice.get("finish_reason")
                if isinstance(finish, str):
                    return finish
    finish = payload.get("finish_reason")
    if isinstance(finish, str):
        return finish
    return None


def _extract_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _resolve_env(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    env_name = name.strip()
    if not env_name or env_name.upper() == "NONE":
        return ""
    return (os.getenv(env_name) or "").strip()


def _is_literal_env_value(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if "://" in candidate:
        return True
    candidate_lower = candidate.lower()
    return any(candidate_lower.startswith(prefix) for prefix in _LITERAL_ENV_VALUE_PREFIXES)


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
        raw = config.raw if isinstance(config.raw, Mapping) else {}
        raw_env = raw.get("env") if isinstance(raw, Mapping) else None

        auth_env_name = ""
        if isinstance(config.auth_env, str):
            auth_env_name = config.auth_env.strip()
        if not auth_env_name or auth_env_name.upper() == "NONE":
            auth_env_name = "OPENROUTER_API_KEY"
        self._configured_auth_env = auth_env_name
        override_candidates: list[str] = []
        resolved_auth_env_name = auth_env_name
        if isinstance(raw_env, Mapping):
            override_name = raw_env.get(auth_env_name)
            if isinstance(override_name, str):
                candidate = override_name.strip()
                if candidate:
                    override_candidates.append(candidate)
            elif isinstance(override_name, Iterable) and not isinstance(override_name, Mapping):
                for item in override_name:
                    if isinstance(item, str):
                        candidate = item.strip()
                        if candidate and candidate not in override_candidates:
                            override_candidates.append(candidate)
        if override_candidates:
            resolved_auth_env_name = override_candidates[0]
        self._auth_env_name = resolved_auth_env_name

        def _resolve_literal_or_env(name: str) -> str:
            if not isinstance(name, str):
                return ""
            candidate = name.strip()
            if not candidate:
                return ""
            if _is_literal_env_value(candidate):
                return candidate
            return _resolve_env(candidate)

        def _resolve_from_env_mapping(default_name: str) -> str:
            if not isinstance(default_name, str):
                return ""
            override_name = None
            if isinstance(raw_env, Mapping):
                override_name = raw_env.get(default_name)
            candidates: list[str] = []
            if isinstance(override_name, str):
                candidate = override_name.strip()
                if candidate:
                    candidates.append(candidate)
            elif isinstance(override_name, Iterable) and not isinstance(override_name, Mapping):
                for item in override_name:
                    if isinstance(item, str):
                        candidate = item.strip()
                        if candidate and candidate not in candidates:
                            candidates.append(candidate)
            for candidate in candidates:
                if _is_literal_env_value(candidate):
                    return candidate
                override_value = _resolve_env(candidate)
                if override_value:
                    return override_value
            return _resolve_env(default_name)

        mapped_api_key = _resolve_from_env_mapping("OPENROUTER_API_KEY")
        seen_candidates: set[str] = set()
        api_key_value = ""
        for candidate_name in override_candidates:
            normalized = candidate_name.strip()
            if not normalized or normalized in seen_candidates:
                continue
            seen_candidates.add(normalized)
            resolved_value = _resolve_literal_or_env(normalized)
            if resolved_value:
                api_key_value = resolved_value
                break
        if not api_key_value:
            configured_value = _resolve_from_env_mapping(auth_env_name)
            if configured_value:
                api_key_value = configured_value
        if not api_key_value and mapped_api_key:
            api_key_value = mapped_api_key
        if not api_key_value:
            api_key_obj = raw.get("api_key")
            if isinstance(api_key_obj, str):
                api_key_value = api_key_obj.strip()
            elif api_key_obj is not None:
                api_key_value = str(api_key_obj).strip()
        if not api_key_value:
            api_key_value = mapped_api_key
        self._api_key = api_key_value
        session_override = raw.get("session") if isinstance(raw, Mapping) else None
        if session_override is None:
            session: SessionProtocol = create_session()
        else:
            session = cast(SessionProtocol, session_override)
        self._session = session
        base_url_value: str | None = None
        mapped_base_url = _resolve_from_env_mapping("OPENROUTER_BASE_URL")
        if mapped_base_url:
            base_url_value = mapped_base_url
        else:
            env_candidate = _resolve_env(raw.get("base_url_env"))
            if env_candidate:
                base_url_value = env_candidate
        if base_url_value is None and isinstance(raw, Mapping):
            base_candidate = raw.get("base_url")
            if isinstance(base_candidate, str):
                base_url_value = base_candidate
        if base_url_value is None and config.endpoint:
            base_url_value = config.endpoint
        default_base = mapped_base_url or "https://openrouter.ai/api/v1"
        self._base_url = (base_url_value or default_base).rstrip("/")
        headers = getattr(self._session, "headers", None)
        if isinstance(headers, MutableMapping):
            headers.setdefault("Content-Type", "application/json")
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
        self._default_timeout = float(config.timeout_s or 30)
        options_from_config = raw.get("options") if isinstance(raw, Mapping) else None
        if isinstance(options_from_config, Mapping):
            self._config_options = {
                key: value
                for key, value in options_from_config.items()
                if key not in _INTERNAL_OPTION_KEYS
            }
        else:
            self._config_options = {}

    def _build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        messages = [dict(message) for message in (request.messages or [])]
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = int(request.max_tokens)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop is not None:
            payload["stop"] = list(request.stop)
        if self._config_options:
            for key, value in self._config_options.items():
                if key in _INTERNAL_OPTION_KEYS:
                    continue
                payload[key] = value
        options = request.options or {}
        if isinstance(options, Mapping):
            for key, value in options.items():
                if key in _INTERNAL_OPTION_KEYS:
                    continue
                payload[key] = value
        return payload

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if not self._api_key:
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
        options = request.options or {}
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
                aggregated, final_payload, finish_reason = self._consume_stream(response)
            else:
                response.raise_for_status()
                data = response.json()
                aggregated = _coerce_text(data)
                final_payload = data
                finish_reason = _coerce_finish_reason(data)
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
        usage = _coerce_usage(usage_payload)
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

    def _consume_stream(
        self, response: Any
    ) -> tuple[str, Mapping[str, Any], str | None]:  # pragma: no cover - exercised via tests
        chunks: list[str] = []
        final_payload: Mapping[str, Any] = {}
        finish_reason: str | None = None
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            try:
                decoded = raw_line.decode("utf-8")
            except AttributeError:  # pragma: no cover - defensive
                decoded = str(raw_line)
            decoded = decoded.strip()
            if not decoded:
                continue
            if decoded.startswith("data:"):
                decoded = decoded[len("data:") :].strip()
            if not decoded or decoded == "[DONE]":
                continue
            try:
                event = json.loads(decoded)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping):
                continue
            choices = event.get("choices")
            if isinstance(choices, Iterable):
                for choice in choices:
                    if not isinstance(choice, Mapping):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, Mapping):
                        content = delta.get("content")
                        if isinstance(content, str):
                            chunks.append(content)
                    elif isinstance(delta, str):
                        chunks.append(delta)
                    message = choice.get("message")
                    if isinstance(message, Mapping):
                        content = message.get("content")
                        if isinstance(content, str):
                            final_payload = event
                    finish = choice.get("finish_reason")
                    if isinstance(finish, str):
                        finish_reason = finish
            usage_payload = event.get("usage")
            if isinstance(usage_payload, Mapping):
                final_payload = event
        if not final_payload:
            text_value = "".join(chunks)
            final_payload = {
                "choices": [
                    {"message": {"role": "assistant", "content": text_value}},
                ]
            }
        aggregated = "".join(chunks) or _coerce_text(final_payload)
        if finish_reason is None:
            finish_reason = _coerce_finish_reason(final_payload)
        return aggregated, final_payload, finish_reason
