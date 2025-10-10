from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
import json
import os
import time
from typing import Any

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from ._requests_compat import create_session, requests_exceptions, SessionProtocol
from .base import BaseProvider

__all__ = ["OpenRouterProvider"]


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


def _normalize_error(exc: Exception) -> Exception:
    if isinstance(exc, TimeoutError):  # pragma: no cover - defensive
        return exc
    if isinstance(exc, requests_exceptions.Timeout):
        return TimeoutError(str(exc))
    if isinstance(exc, requests_exceptions.ConnectionError):
        return RetriableError(str(exc))
    if isinstance(exc, requests_exceptions.HTTPError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        try:
            code = int(status) if status is not None else None
        except (TypeError, ValueError):  # pragma: no cover - defensive
            code = None
        message = str(exc)
        if code in {401, 403}:
            return AuthError(message)
        if code == 429:
            return RateLimitError(message)
        if code in {408, 504}:
            return TimeoutError(message)
        if code is not None and code >= 500:
            return RetriableError(message)
        return RetriableError(message)
    if isinstance(exc, requests_exceptions.RequestException):
        return RetriableError(str(exc))
    return exc


class OpenRouterProvider(BaseProvider):
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        session: SessionProtocol | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(name="openrouter", model=model)
        self._api_key = (api_key or os.getenv("OPENROUTER_API_KEY") or "").strip()
        self._session = session or create_session()
        self._base_url = (
            base_url or os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        ).rstrip("/")
        headers = getattr(self._session, "headers", None)
        if isinstance(headers, MutableMapping):
            headers.setdefault("Content-Type", "application/json")
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

    def _build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.chat_messages,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = int(request.max_tokens)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop is not None:
            payload["stop"] = list(request.stop)
        options = request.options
        if isinstance(options, Mapping):
            for key, value in options.items():
                if key == "stream":
                    continue
                payload.setdefault(key, value)
        return payload

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        timeout = request.timeout_s if request.timeout_s is not None else 30.0
        stream = False
        if isinstance(request.options, Mapping):
            stream = bool(request.options.get("stream"))
        payload = self._build_payload(request)
        if stream:
            payload.setdefault("stream", True)
        url = f"{self._base_url}/chat/completions"
        ts0 = time.time()
        try:
            response = self._session.post(url, json=payload, stream=stream, timeout=timeout)
        except Exception as exc:  # pragma: no cover - translated below
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
    ) -> tuple[str, Mapping[str, Any], str | None]:  # pragma: no cover - covered via tests
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
