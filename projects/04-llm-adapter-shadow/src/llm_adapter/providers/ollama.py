"""Ollama provider with automatic model management."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ..errors import ConfigError
from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI, TokenUsage
from .ollama_http import OllamaHTTPClient
from .ollama_http import SessionProtocol as _SessionProtocol
from .ollama_http import requests_exceptions as _requests_exceptions

requests_exceptions = _requests_exceptions

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
        session: _SessionProtocol | None = None,
        timeout: float = 60.0,
        pull_timeout: float = 300.0,
        auto_pull: bool = True,
    ) -> None:
        # Factory/CLI で ``ProviderRequest.model`` に設定される推奨デフォルトを保持。
        self._model = model
        self._name = name or f"ollama:{model}"
        env_host = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
        self._host: str = host or env_host or DEFAULT_HOST
        self._http = OllamaHTTPClient(
            host=self._host,
            session=session,
            timeout=timeout,
            pull_timeout=pull_timeout,
            auto_pull=auto_pull,
        )
        self._session = self._http.session
        self._timeout = timeout
        self._auto_pull = auto_pull
        self._ready_models = self._http.ready_models

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    # ------------------------------------------------------------------
    # ProviderSPI implementation
    # ------------------------------------------------------------------
    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        model_name = request.model
        if not isinstance(model_name, str):
            raise ConfigError("OllamaProvider requires request.model to be set")
        model_name = model_name.strip()
        if not model_name:
            raise ConfigError("OllamaProvider requires request.model to be set")
        self._http.ensure_model(model_name)

        def _coerce_content(entry: Mapping[str, Any]) -> str:
            content = entry.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, Sequence) and not isinstance(
                content, bytes | bytearray
            ):
                parts = [part for part in content if isinstance(part, str)]
                return "\n".join(parts)
            if content is None:
                return ""
            return str(content)

        messages_payload: list[dict[str, str]] = []
        for message in request.chat_messages:
            if not isinstance(message, Mapping):
                continue
            role = str(message.get("role", "user")) or "user"
            text = _coerce_content(message).strip()
            if text:
                messages_payload.append({"role": role, "content": text})

        if not messages_payload and request.prompt_text:
            messages_payload.append({"role": "user", "content": request.prompt_text})

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages_payload,
            "stream": False,
        }

        # --- options 統合（新SPI + 互換） ---
        options_payload: dict[str, Any] = {}
        if request.max_tokens is not None:
            options_payload["num_predict"] = int(request.max_tokens)
        if request.temperature is not None:
            options_payload["temperature"] = float(request.temperature)
        if request.top_p is not None:
            options_payload["top_p"] = float(request.top_p)
        if request.stop:
            options_payload["stop"] = list(request.stop)

        # timeout の優先度: request.timeout_s > options.request_timeout_s > default
        timeout_override: float | None = None
        if request.timeout_s is not None:
            timeout_override = float(request.timeout_s)

        if request.options and isinstance(request.options, Mapping):
            opt_items = dict(request.options.items())

            # timeout 上書き (options 側)
            for key in ("request_timeout_s", "REQUEST_TIMEOUT_S"):
                if key in opt_items:
                    raw_timeout = opt_items.pop(key)
                    if raw_timeout is not None and timeout_override is None:
                        try:
                            timeout_override = float(raw_timeout)
                        except (TypeError, ValueError) as exc:
                            raise ConfigError(
                                "request_timeout_s must be a number"
                            ) from exc
                    break

            # 衝突しうるトップレベルは除去
            for k in ("model", "messages", "prompt"):
                opt_items.pop(k, None)

            # ネストした options をマージ
            nested_opts = opt_items.pop("options", None)
            if isinstance(nested_opts, Mapping):
                options_payload.update(dict(nested_opts))

            # 残りはトップレベルに反映（Ollamaが理解する追加パラメータ）
            for k, v in opt_items.items():
                payload[k] = v

        if options_payload:
            payload["options"] = {**options_payload, **payload.get("options", {})}

        ts0 = time.time()
        payload_json = self._http.chat(payload, timeout=timeout_override)

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
