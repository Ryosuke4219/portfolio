"""Google Gemini プロバイダ実装。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
import time
from typing import Any, cast, Protocol

from ..config import ProviderConfig
from ..provider_spi import ProviderRequest
from . import BaseProvider, ProviderResponse
from .gemini_support import (
    coerce_raw_output as _coerce_raw_output,
    extract_output_text as _extract_output_text,
    extract_usage as _extract_usage,
    invoke_gemini as _invoke_gemini,
    normalize_gemini_exception as _normalize_gemini_exception,
    prepare_generation_config as _prepare_generation_config,
    prepare_safety_settings as _prepare_safety_settings,
    resolve_api_key as _resolve_api_key,
)

__all__ = ["GeminiProvider"]

class _GenAIClient(Protocol):
    def __init__(self, api_key: str) -> None:  # pragma: no cover - interface only
        ...


class _GenAIModule(Protocol):
    Client: type[_GenAIClient]


try:  # pragma: no cover - 実行環境により SDK が存在しない場合がある
    _imported_genai = import_module("google.genai")
except ModuleNotFoundError:  # pragma: no cover - SDK 未導入時
    _genai: _GenAIModule | None = None
else:
    _genai = cast(_GenAIModule, _imported_genai)


class GeminiProvider(BaseProvider):
    """Google Gemini (Generative AI) 向けプロバイダ。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if _genai is None:  # pragma: no cover - SDK 未導入時
            raise ImportError("google-genai がインストールされていません")
        api_key = _resolve_api_key(config.auth_env)
        client_cls: type[_GenAIClient] = _genai.Client
        self._client: _GenAIClient = client_cls(api_key=api_key)
        self._model = config.model
        base_config = _prepare_generation_config(config)
        self._generation_config: Mapping[str, Any] | None = (
            dict(base_config) if base_config else None
        )
        safety_settings = _prepare_safety_settings(config)
        self._safety_settings: Sequence[Mapping[str, Any]] | None = (
            list(safety_settings) if safety_settings else None
        )

    def generate(self, prompt: str) -> ProviderResponse:
        request = ProviderRequest(model=self._model, prompt=prompt)
        return self.invoke(request)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        options = dict(request.options)
        contents_option = options.get("contents")
        contents: Sequence[Mapping[str, Any]] | None = None
        if isinstance(contents_option, Sequence):
            normalized_contents = [
                dict(item) for item in contents_option if isinstance(item, Mapping)
            ]
            if normalized_contents:
                contents = normalized_contents
        if contents is None:
            normalized_messages = []
            for message in request.messages or ():
                if not isinstance(message, Mapping):
                    continue
                role = str(message.get("role", "user") or "user")
                parts = message.get("parts")
                if isinstance(parts, Sequence):
                    normalized_messages.append({"role": role, "parts": list(parts)})
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    normalized_messages.append(
                        {"role": role, "parts": [{"text": content}]}
                    )
            if not normalized_messages and request.prompt:
                normalized_messages = [
                    {"role": "user", "parts": [{"text": request.prompt}]}
                ]
            contents = normalized_messages or None
        generation_config: dict[str, Any] = {}
        if self._generation_config:
            generation_config.update(self._generation_config)
        options_config = options.get("generation_config")
        if isinstance(options_config, Mapping):
            generation_config.update(options_config)
        if request.temperature is not None:
            generation_config["temperature"] = float(request.temperature)
        if request.top_p is not None:
            generation_config["top_p"] = float(request.top_p)
        if request.max_tokens is not None:
            generation_config["max_output_tokens"] = int(request.max_tokens)
        generation_config_mapping: Mapping[str, Any] | None = (
            generation_config if generation_config else None
        )
        safety_settings: Sequence[Mapping[str, Any]] | None = None
        if self._safety_settings:
            safety_settings = [dict(item) for item in self._safety_settings]
        options_safety = options.get("safety_settings")
        if isinstance(options_safety, Sequence):
            normalized_safety = [
                dict(item) for item in options_safety if isinstance(item, Mapping)
            ]
            if normalized_safety:
                safety_settings = normalized_safety
        ts0 = time.time()
        try:
            response = _invoke_gemini(
                self._client,
                request.model or self._model,
                contents,
                generation_config_mapping,
                safety_settings,
            )
        except Exception as exc:  # pragma: no cover - 実行時例外は発生環境依存
            normalized = _normalize_gemini_exception(exc)
            raise normalized from exc
        latency_ms = int((time.time() - ts0) * 1000)
        prompt_text = request.prompt
        output_text = _extract_output_text(response)
        prompt_tokens, output_tokens = _extract_usage(response, prompt_text, output_text)
        raw_output = _coerce_raw_output(response)
        return ProviderResponse(
            output_text=output_text,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_output=dict(raw_output) if isinstance(raw_output, Mapping) else None,
        )
