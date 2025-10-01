"""Ollama provider with automatic model management."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import time
from typing import Any

from ..errors import ConfigError, ProviderSkip, RetriableError
from ..provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from ._requests_compat import (
    create_session,
    requests_exceptions,
    SessionProtocol,
)
from .base import BaseProvider
from .ollama_client import OllamaClient

DEFAULT_HOST = "http://127.0.0.1:11434"
__all__ = ["OllamaProvider", "DEFAULT_HOST", "requests_exceptions"]


def _token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
    prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(payload.get("eval_count", 0) or 0)
    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


class OllamaProvider(BaseProvider):
    """Provider backed by the local Ollama HTTP API."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        host: str | None = None,
        session: SessionProtocol | None = None,
        client: OllamaClient | None = None,
        timeout: float = 60.0,
        pull_timeout: float = 300.0,
        auto_pull: bool = True,
    ) -> None:
        provider_name = name or f"ollama:{model}"
        super().__init__(name=provider_name, model=model)
        env_host = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
        self._host: str = host or env_host or DEFAULT_HOST

        timeout_env = os.environ.get("OLLAMA_TIMEOUT_S")
        if timeout_env is not None:
            try:
                timeout = float(timeout_env)
            except (TypeError, ValueError):
                pass
        pull_timeout_env = os.environ.get("OLLAMA_PULL_TIMEOUT_S")
        if pull_timeout_env is not None:
            try:
                pull_timeout = float(pull_timeout_env)
            except (TypeError, ValueError):
                pass

        self._timeout = timeout
        self._pull_timeout = pull_timeout
        self._offline = (
            os.environ.get("LLM_ADAPTER_OFFLINE") == "1"
            or os.environ.get("CI", "").lower() == "true"
        )
        session_provided = session is not None
        client_provided = client is not None
        allow_network = session_provided or client_provided
        auto_pull_env = os.environ.get("OLLAMA_AUTO_PULL")
        if auto_pull_env is not None and auto_pull_env.strip() == "0" and not allow_network:
            auto_pull = False

        self._auto_pull = auto_pull
        self._allow_network = allow_network
        self._ready_models: set[str] = set()
        if client is None:
            if session is None:
                session = create_session()
            client = OllamaClient(
                host=self._host,
                session=session,
                timeout=self._timeout,
                pull_timeout=self._pull_timeout,
            )
        self._client = client

    def _ensure_model(self, model_name: str) -> None:
        if self._offline and not self._allow_network:
            raise ProviderSkip("offline mode: ollama network calls disabled")

        if model_name in self._ready_models:
            return

        show_response = self._client.show({"model": model_name})
        if show_response.status_code == 200:
            self._ready_models.add(model_name)
            show_response.close()
            return
        show_response.close()

        if not self._auto_pull:
            raise RetriableError(f"ollama model not available: {model_name}")

        with self._client.pull({"model": model_name}) as pull_response:
            # Drain the streaming response to complete the pull.
            for _ in pull_response.iter_lines():  # pragma: no cover - network interaction
                pass

        # Verify again with a short retry window.
        for _ in range(10):
            show_after = self._client.show({"model": model_name})
            if show_after.status_code == 200:
                self._ready_models.add(model_name)
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {model_name}")

    # ------------------------------------------------------------------
    # ProviderSPI implementation
    # ------------------------------------------------------------------
    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if self._offline and not self._allow_network:
            raise ProviderSkip("offline mode: ollama network calls disabled")

        model_name = request.model
        if not isinstance(model_name, str):
            raise ConfigError("OllamaProvider requires request.model to be set")
        model_name = model_name.strip()
        if not model_name:
            raise ConfigError("OllamaProvider requires request.model to be set")
        self._ensure_model(model_name)

        def _coerce_content(entry: Mapping[str, Any]) -> str:
            content = entry.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, Sequence) and not isinstance(content, bytes | bytearray):
                parts = [part for part in content if isinstance(part, str)]
                return "\n".join(parts)
            if content is None:
                return ""
            return str(content)

        messages_payload: list[dict[str, str]] = []
        for chat_message in request.chat_messages:
            if not isinstance(chat_message, Mapping):
                continue
            role = str(chat_message.get("role", "user")) or "user"
            text = _coerce_content(chat_message).strip()
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

        stream_flag = bool(payload.get("stream"))
        payload["stream"] = stream_flag

        ts0 = time.time()
        response = self._client.chat(payload, timeout=timeout_override, stream=stream_flag)

        try:
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

