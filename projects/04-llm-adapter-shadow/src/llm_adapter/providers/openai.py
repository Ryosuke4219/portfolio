from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from ..errors import RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from ._requests_compat import SessionProtocol, create_session, requests_exceptions
from .base import BaseProvider

__all__ = ["OpenAIProvider"]


def _coerce_text(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    collected: list[str] = []
    output = payload.get("output")
    if isinstance(output, Iterable):
        for entry in output:
            if not isinstance(entry, Mapping):
                continue
            content = entry.get("content")
            if isinstance(content, Iterable):
                for part in content:
                    if isinstance(part, Mapping):
                        text = part.get("text") or part.get("value")
                        if isinstance(text, str):
                            collected.append(text)
    if collected:
        return "".join(collected)
    text_value = payload.get("text") or payload.get("output_text")
    if isinstance(text_value, str):
        return text_value
    choices = payload.get("choices")
    if isinstance(choices, Iterable):
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    collected.append(content)
            text = choice.get("text")
            if isinstance(text, str):
                collected.append(text)
    return "".join(collected)


def _coerce_usage(payload: Mapping[str, Any] | None) -> TokenUsage:
    if not isinstance(payload, Mapping):
        return TokenUsage()
    prompt_tokens = payload.get("input_tokens") or payload.get("prompt_tokens") or 0
    completion_tokens = payload.get("output_tokens") or payload.get("completion_tokens") or 0
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
    finish = payload.get("finish_reason")
    if isinstance(finish, str):
        return finish
    choices = payload.get("choices")
    if isinstance(choices, Iterable):
        for choice in choices:
            if isinstance(choice, Mapping):
                candidate = choice.get("finish_reason")
                if isinstance(candidate, str):
                    return candidate
    return None


def _normalize_error(exc: Exception) -> Exception:
    if isinstance(exc, TimeoutError):  # pragma: no cover - defensive (already mapped)
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
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            code = None
        message = str(exc)
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


class OpenAIProvider(BaseProvider):
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        organization: str | None = None,
        session: SessionProtocol | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(name="openai", model=model)
        self._api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        self._organization = (organization or os.getenv("OPENAI_ORGANIZATION") or "").strip()
        self._session = session or create_session()
        self._base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        headers = getattr(self._session, "headers", None)
        if isinstance(headers, MutableMapping):
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            headers.setdefault("Content-Type", "application/json")
            if self._organization:
                headers["OpenAI-Organization"] = self._organization

    def _build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": request.model, "input": request.prompt_text}
        messages = request.chat_messages
        if messages:
            payload["messages"] = messages
        if request.max_tokens is not None:
            payload["max_output_tokens"] = int(request.max_tokens)
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
        url = f"{self._base_url}/responses"
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
        usage = _coerce_usage(final_payload.get("usage") if isinstance(final_payload, Mapping) else None)
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

    def _consume_stream(self, response: Any) -> tuple[str, Mapping[str, Any], str | None]:
        chunks: list[str] = []
        final_payload: Mapping[str, Any] = {}
        finish_reason: str | None = None
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            try:
                decoded = raw_line.decode("utf-8")
            except AttributeError:  # pragma: no cover - already bytes in tests
                decoded = str(raw_line)
            decoded = decoded.strip()
            if not decoded:
                continue
            try:
                event = json.loads(decoded)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping):
                continue
            event_type = event.get("type")
            if event_type and "delta" in event_type:
                delta = event.get("delta")
                if isinstance(delta, str):
                    chunks.append(delta)
                continue
            if event_type == "response.completed":
                response_payload = event.get("response")
                if isinstance(response_payload, Mapping):
                    final_payload = response_payload
                finish = event.get("finish_reason")
                if isinstance(finish, str):
                    finish_reason = finish
        if not final_payload:
            text_value = "".join(chunks)
            final_payload = {
                "output": [
                    {"content": [{"type": "output_text", "text": text_value}]}
                ]
            }
        aggregated = "".join(chunks) or _coerce_text(final_payload)
        if finish_reason is None:
            finish_reason = _coerce_finish_reason(final_payload)
        return aggregated, final_payload, finish_reason
