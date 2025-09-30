"""Google Gemini プロバイダ実装。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import time
from typing import Any

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

try:  # pragma: no cover - 実行環境により SDK が存在しない場合がある
    from google import genai as _genai  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - SDK 未導入時
    _genai = None  # type: ignore[assignment]


class GeminiProvider(BaseProvider):
    """Google Gemini (Generative AI) 向けプロバイダ。"""

    def __init__(self, config):
        super().__init__(config)
        if _genai is None:  # pragma: no cover - SDK 未導入時
            raise ImportError("google-genai がインストールされていません")
        api_key = _resolve_api_key(config.auth_env)
        self._client = _genai.Client(api_key=api_key)  # type: ignore[call-arg]
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
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        ts0 = time.time()
        try:
            response = _invoke_gemini(
                self._client,
                self._model,
                contents,
                self._generation_config,
                self._safety_settings,
            )
        except Exception as exc:  # pragma: no cover - 実行時例外は発生環境依存
            normalized = _normalize_gemini_exception(exc)
            raise normalized from exc
        latency_ms = int((time.time() - ts0) * 1000)
        output_text = _extract_output_text(response)
        prompt_tokens, output_tokens = _extract_usage(response, prompt, output_text)
        raw_output = _coerce_raw_output(response)
        return ProviderResponse(
            output_text=output_text,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_output=dict(raw_output) if isinstance(raw_output, Mapping) else None,
        )
