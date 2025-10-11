"""Ollama provider with automatic model management."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import time
from typing import Any, cast

from ..config import ProviderConfig
from ..errors import ConfigError, ProviderSkip, RetriableError, SkipReason
from ..provider_spi import ProviderRequest, TokenUsage
from . import BaseProvider, ProviderResponse
from ._requests_compat import SessionProtocol, create_session, requests_exceptions
from .ollama_client import OllamaClient

DEFAULT_HOST = "http://127.0.0.1:11434"


def _token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
    prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(payload.get("eval_count", 0) or 0)
    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


class OllamaProvider(BaseProvider):
    """Provider backed by the local Ollama HTTP API."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        raw = config.raw
        host_candidate: str | None = None
        if isinstance(raw, Mapping):
            raw_host = raw.get("host") or raw.get("base_url")
            if isinstance(raw_host, str):
                host_candidate = raw_host
            elif raw_host is not None:
                host_candidate = str(raw_host)
        if host_candidate is None and config.endpoint:
            host_candidate = config.endpoint
        env_host = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST")
        host_value = (host_candidate or env_host or DEFAULT_HOST).strip()
        if not host_value:
            raise ProviderSkip(
                "ollama: endpoint not configured",
                reason=SkipReason.MISSING_OLLAMA_ENDPOINT,
            )
        self._host = host_value

        timeout_default = float(config.timeout_s or 60)
        pull_timeout_default = 300.0
        timeout_env = os.getenv("OLLAMA_TIMEOUT_S")
        pull_timeout_env = os.getenv("OLLAMA_PULL_TIMEOUT_S")
        timeout_value = _coerce_float(timeout_env, timeout_default)
        pull_timeout_value = _coerce_float(pull_timeout_env, pull_timeout_default)
        if isinstance(raw, Mapping):
            if "timeout_s" in raw:
                timeout_value = _coerce_float(raw.get("timeout_s"), timeout_value)
            if "pull_timeout_s" in raw:
                pull_timeout_value = _coerce_float(raw.get("pull_timeout_s"), pull_timeout_value)
        self._timeout = timeout_value
        self._pull_timeout = pull_timeout_value

        offline_env = os.getenv("LLM_ADAPTER_OFFLINE")
        ci_flag = os.getenv("CI", "").strip().lower() == "true"
        if offline_env is not None:
            normalized_offline = offline_env.strip().lower()
            if normalized_offline in {"0", "false"}:
                self._offline = False
            elif normalized_offline in {"1", "true", "yes", "on"}:
                self._offline = True
            else:
                self._offline = _coerce_bool(offline_env, True)
        else:
            self._offline = ci_flag

        session_override = raw.get("session") if isinstance(raw, Mapping) else None
        client_override = raw.get("client") if isinstance(raw, Mapping) else None
        allow_network = session_override is not None or client_override is not None

        auto_pull_env = os.getenv("OLLAMA_AUTO_PULL")
        auto_pull_default = True
        if isinstance(raw, Mapping) and "auto_pull" in raw:
            auto_pull_default = _coerce_bool(raw.get("auto_pull"), auto_pull_default)
        if auto_pull_env is not None and auto_pull_env.strip() == "0" and not allow_network:
            auto_pull_default = False
        self._auto_pull = auto_pull_default
        self._allow_network = allow_network
        self._ready_models: set[str] = set()

        if client_override is not None:
            client = cast(OllamaClient, client_override)
        else:
            if session_override is not None:
                session = cast(SessionProtocol, session_override)
            else:
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
            raise ProviderSkip(
                "offline mode: ollama network calls disabled",
                reason=SkipReason.OLLAMA_OFFLINE,
            )
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
            for _ in pull_response.iter_lines():  # pragma: no cover - network interaction
                pass

        for _ in range(10):
            show_after = self._client.show({"model": model_name})
            if show_after.status_code == 200:
                self._ready_models.add(model_name)
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {model_name}")

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if self._offline and not self._allow_network:
            raise ProviderSkip(
                "offline mode: ollama network calls disabled",
                reason=SkipReason.OLLAMA_OFFLINE,
            )

        model_name = request.model.strip()
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
        for chat_message in request.messages or []:
            if not isinstance(chat_message, Mapping):
                continue
            role = str(chat_message.get("role", "user")) or "user"
            text = _coerce_content(chat_message).strip()
            if text:
                messages_payload.append({"role": role, "content": text})

        if not messages_payload and request.prompt:
            messages_payload.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages_payload,
        }
        stream = False
        options_payload: dict[str, Any] = {}
        if request.max_tokens is not None:
            options_payload["num_predict"] = int(request.max_tokens)
        if request.temperature is not None:
            options_payload["temperature"] = float(request.temperature)
        if request.top_p is not None:
            options_payload["top_p"] = float(request.top_p)
        if request.stop:
            options_payload["stop"] = list(request.stop)

        timeout_override: float | None = None
        if request.timeout_s is not None:
            timeout_override = float(request.timeout_s)

        options = request.options or {}
        if isinstance(options, Mapping):
            opt_items = dict(options.items())

            if "stream" in opt_items:
                raw_stream = opt_items.pop("stream")
                if raw_stream is not None:
                    stream = bool(raw_stream)

            for key in ("request_timeout_s", "REQUEST_TIMEOUT_S"):
                if key in opt_items:
                    raw_timeout = opt_items.pop(key)
                    if raw_timeout is not None and timeout_override is None:
                        try:
                            timeout_override = float(raw_timeout)
                        except (TypeError, ValueError) as exc:
                            raise ConfigError("request_timeout_s must be a number") from exc
                    break

            for top_key in ("model", "messages", "prompt"):
                opt_items.pop(top_key, None)

            nested_opts = opt_items.pop("options", None)
            if isinstance(nested_opts, Mapping):
                options_payload.update(dict(nested_opts))

            for key, value in opt_items.items():
                payload[key] = value

        if options_payload:
            payload["options"] = {**options_payload, **payload.get("options", {})}

        ts0 = time.time()
        response = self._client.chat(payload, timeout=timeout_override, stream=stream)

        try:
            payload_json = response.json()
        except ValueError as exc:
            raise RetriableError("invalid JSON from Ollama") from exc
        finally:
            response.close()

        if not isinstance(payload_json, Mapping):
            raise RetriableError("invalid JSON structure from Ollama")

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


__all__ = ["OllamaProvider", "DEFAULT_HOST", "requests_exceptions"]
