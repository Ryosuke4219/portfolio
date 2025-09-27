"""Ollama provider with automatic model management."""

from __future__ import annotations

import os
import time
from functools import partial
from typing import Mapping, cast

from ...errors import AuthError, ConfigError, RateLimitError, RetriableError, TimeoutError
from ...provider_spi import ProviderRequest, ProviderResponse, ProviderSPI, TokenUsage
from .http import SessionProtocol, create_default_session, requests_exceptions, send_request
from .models import ensure_model, RequestCallable
from .payloads import prepare_chat_payload

DEFAULT_HOST = "http://127.0.0.1:11434"
__all__ = ["OllamaProvider", "DEFAULT_HOST"]


def _token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
    prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(payload.get("eval_count", 0) or 0)
    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


class OllamaProvider(ProviderSPI):
    """Provider backed by the local Ollama HTTP API."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        host: str | None = None,
        session: SessionProtocol | None = None,
        timeout: float = 60.0,
        pull_timeout: float = 300.0,
        auto_pull: bool = True,
    ) -> None:
        self._model = model
        self._name = name or f"ollama:{model}"
        env_host = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
        self._host: str = host or env_host or DEFAULT_HOST
        if session is None:
            session = create_default_session()
        self._session = session
        self._timeout = timeout
        self._pull_timeout = pull_timeout
        self._auto_pull = auto_pull
        self._ready_models: set[str] = set()
        self._request_fn: RequestCallable = cast(
            RequestCallable,
            partial(send_request, self._session, self._host, self._timeout),
        )

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def _validate_model(self, request: ProviderRequest) -> str:
        model_name = request.model
        if not isinstance(model_name, str):
            raise ConfigError("OllamaProvider requires request.model to be set")
        model_name = model_name.strip()
        if not model_name:
            raise ConfigError("OllamaProvider requires request.model to be set")
        return model_name

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        model_name = self._validate_model(request)
        ensure_model(
            model_name,
            ready_models=self._ready_models,
            auto_pull=self._auto_pull,
            pull_timeout=self._pull_timeout,
            request=self._request_fn,
        )

        payload, timeout_override = prepare_chat_payload(request, model_name)

        ts0 = time.time()
        response = self._request_fn("/api/chat", payload, timeout=timeout_override)

        try:
            try:
                response.raise_for_status()
            except requests_exceptions.HTTPError as exc:
                status = response.status_code
                if status in {401, 403}:
                    raise AuthError(str(exc)) from exc
                if status == 429:
                    raise RateLimitError(str(exc)) from exc
                if status in {408, 504}:
                    raise TimeoutError(str(exc)) from exc
                if status >= 500:
                    raise RetriableError(str(exc)) from exc
                raise RetriableError(str(exc)) from exc

            payload_json = response.json()
        except ValueError as exc:
            raise RetriableError("invalid JSON from Ollama") from exc
        finally:
            response.close()

        message = payload_json.get("message")
        text = ""
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                text = content
        if not isinstance(text, str):
            text = ""

        latency_ms = int((time.time() - ts0) * 1000)
        usage = _token_usage_from_payload(payload_json)

        return ProviderResponse(
            text=text,
            token_usage=usage,
            latency_ms=latency_ms,
            model=model_name,
            finish_reason=payload_json.get("done_reason"),
            raw=payload_json,
        )
