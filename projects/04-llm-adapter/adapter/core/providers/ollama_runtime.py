"""Runtime helpers for interacting with the Ollama API."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import time
from typing import Any

from ..errors import ConfigError, ProviderSkip, RetriableError, SkipReason
from ..provider_spi import ProviderRequest, TokenUsage
from . import ProviderResponse
from .ollama_client import OllamaClient
from .ollama_connection import OllamaConnectionHelper

__all__ = ["OllamaRuntimeHelper"]


class OllamaRuntimeHelper:
    """Utility helpers for payload construction and Ollama responses."""

    @staticmethod
    def ensure_network_access(connection: OllamaConnectionHelper) -> None:
        if connection.offline and not connection.allow_network:
            raise ProviderSkip(
                "offline mode: ollama network calls disabled",
                reason=SkipReason.OLLAMA_OFFLINE,
            )

    @staticmethod
    def ensure_model(
        connection: OllamaConnectionHelper,
        client: OllamaClient,
        ready_models: set[str],
        model_name: str,
    ) -> None:
        OllamaRuntimeHelper.ensure_network_access(connection)
        if model_name in ready_models:
            return

        show_response = client.show({"model": model_name})
        if show_response.status_code == 200:
            ready_models.add(model_name)
            show_response.close()
            return
        show_response.close()

        if not connection.auto_pull:
            raise RetriableError(f"ollama model not available: {model_name}")

        with client.pull({"model": model_name}) as pull_response:
            for _ in pull_response.iter_lines():  # pragma: no cover - network interaction
                pass

        for _ in range(10):
            show_after = client.show({"model": model_name})
            if show_after.status_code == 200:
                ready_models.add(model_name)
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {model_name}")

    @staticmethod
    def build_chat_payload(
        model_name: str, request: ProviderRequest
    ) -> tuple[dict[str, Any], bool, float | None]:
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

        return payload, stream, timeout_override

    @staticmethod
    def invoke_chat(
        client: OllamaClient,
        payload: Mapping[str, Any],
        *,
        stream: bool,
        timeout_override: float | None,
    ) -> tuple[Mapping[str, Any], int]:
        ts0 = time.time()
        response = client.chat(payload, timeout=timeout_override, stream=stream)

        if stream:
            try:
                payload_json = OllamaRuntimeHelper._consume_stream_response(response)
            finally:
                response.close()
        else:
            try:
                try:
                    payload_json = response.json()
                except ValueError as exc:  # pragma: no cover - 非ストリーム時の保険
                    raise RetriableError("invalid JSON from Ollama") from exc
            finally:
                response.close()

        if not isinstance(payload_json, Mapping):
            raise RetriableError("invalid JSON structure from Ollama")

        latency_ms = int((time.time() - ts0) * 1000)
        return payload_json, latency_ms

    @staticmethod
    def build_response(
        payload_json: Mapping[str, Any],
        *,
        model_name: str,
        latency_ms: int,
    ) -> ProviderResponse:
        message = payload_json.get("message")
        text = ""
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                text = content
        if not isinstance(text, str):
            text = ""

        usage = OllamaRuntimeHelper.token_usage_from_payload(payload_json)

        return ProviderResponse(
            text=text,
            token_usage=usage,
            latency_ms=latency_ms,
            model=model_name,
            finish_reason=payload_json.get("done_reason"),
            raw=payload_json,
        )

    @staticmethod
    def token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
        prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(payload.get("eval_count", 0) or 0)
        return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)

    @staticmethod
    def _consume_stream_response(response: Any) -> dict[str, Any]:
        parts: list[str] = []
        final_payload: dict[str, Any] | None = None
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                try:
                    decoded = raw_line.decode("utf-8")
                except UnicodeDecodeError as exc:  # pragma: no cover - 不正なUTF-8防御
                    raise RetriableError("invalid UTF-8 from Ollama stream") from exc
            else:
                decoded = str(raw_line)
            decoded = decoded.strip()
            if not decoded:
                continue
            try:
                chunk = json.loads(decoded)
            except ValueError as exc:
                raise RetriableError("invalid JSON from Ollama") from exc
            if not isinstance(chunk, Mapping):
                continue
            final_payload = dict(chunk)
            message = chunk.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    parts.append(content)

        if final_payload is None:
            raise RetriableError("empty stream from Ollama")

        if parts:
            message_payload: dict[str, Any]
            raw_message = final_payload.get("message")
            if isinstance(raw_message, Mapping):
                message_payload = dict(raw_message)
            else:
                message_payload = {}
            message_payload["content"] = "".join(parts)
            final_payload["message"] = message_payload

        return final_payload
