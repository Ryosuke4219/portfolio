"""Google Gemini プロバイダ実装。"""

from __future__ import annotations

import os
import time
from typing import Any, Mapping, MutableMapping, Sequence

from ..config import ProviderConfig
from . import BaseProvider, ProviderResponse

__all__ = ["GeminiProvider"]

try:  # pragma: no cover - 実行環境により SDK が存在しない場合がある
    from google import genai as _genai  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - SDK 未導入時
    _genai = None  # type: ignore[assignment]


def _resolve_api_key(env_name: str | None) -> str:
    if not env_name:
        raise RuntimeError("Gemini プロバイダを利用するには auth_env に API キーの環境変数を指定してください")
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(f"Gemini API キーが環境変数 '{env_name}' に見つかりません")
    return value


def _prepare_generation_config(config_obj: ProviderConfig) -> MutableMapping[str, Any]:
    config: MutableMapping[str, Any] = {}
    raw = config_obj.raw.get("generation_config")
    if isinstance(raw, Mapping):
        config.update(raw)
    if config_obj.temperature:
        config.setdefault("temperature", float(config_obj.temperature))
    if config_obj.top_p and config_obj.top_p < 1.0:
        config.setdefault("top_p", float(config_obj.top_p))
    if config_obj.max_tokens:
        config.setdefault("max_output_tokens", int(config_obj.max_tokens))
    return config


def _prepare_safety_settings(config_obj: ProviderConfig) -> Sequence[Mapping[str, Any]] | None:
    raw = config_obj.raw.get("safety_settings")
    if isinstance(raw, Sequence):
        candidates: list[Mapping[str, Any]] = []
        for item in raw:
            if isinstance(item, Mapping):
                candidates.append(dict(item))
        if candidates:
            return candidates
    return None


def _call_with_optional_safety(
    func: Any,
    *,
    model: str,
    config: Mapping[str, Any] | None,
    safety_settings: Sequence[Mapping[str, Any]] | None,
    payload_key: str,
    payload: Any,
) -> Any:
    kwargs: dict[str, Any] = {"model": model, payload_key: payload}
    if config:
        kwargs["config"] = config
    if safety_settings:
        kwargs["safety_settings"] = safety_settings
    try:
        return func(**kwargs)
    except TypeError as exc:  # pragma: no cover - 旧 SDK 互換
        if safety_settings and "safety_settings" in str(exc):
            kwargs.pop("safety_settings", None)
            return func(**kwargs)
        raise


def _invoke_gemini(client: Any, model: str, contents: Sequence[Mapping[str, Any]] | None, config: Mapping[str, Any] | None, safety_settings: Sequence[Mapping[str, Any]] | None) -> Any:
    models_api = getattr(client, "models", None)
    if models_api and hasattr(models_api, "generate_content"):
        func = getattr(models_api, "generate_content")
        return _call_with_optional_safety(
            func,
            model=model,
            config=config,
            safety_settings=safety_settings,
            payload_key="contents",
            payload=contents,
        )
    responses_api = getattr(client, "responses", None)
    if responses_api and hasattr(responses_api, "generate"):
        func = getattr(responses_api, "generate")
        return _call_with_optional_safety(
            func,
            model=model,
            config=config,
            safety_settings=safety_settings,
            payload_key="input",
            payload=contents,
        )
    raise AttributeError("Gemini クライアントが対応する generate メソッドを提供していません")


def _extract_usage(response: Any, prompt: str, output_text: str) -> tuple[int, int]:
    prompt_tokens = 0
    output_tokens = 0
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    else:
        payload = None
        if hasattr(response, "to_dict"):
            try:
                payload = response.to_dict()
            except Exception:  # pragma: no cover - defensive
                payload = None
        if isinstance(payload, Mapping):
            usage_dict = payload.get("usage_metadata")
            if isinstance(usage_dict, Mapping):
                prompt_tokens = int(usage_dict.get("input_tokens", 0) or 0)
                output_tokens = int(usage_dict.get("output_tokens", 0) or 0)
    if prompt_tokens <= 0:
        prompt_tokens = max(1, len(prompt.split()))
    if output_tokens <= 0:
        tokens = len(output_text.split())
        output_tokens = max(1, tokens) if tokens else 0
    return prompt_tokens, output_tokens


def _extract_output_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, Sequence):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate_text = candidate.get("text")
                if isinstance(candidate_text, str) and candidate_text.strip():
                    return candidate_text
            text_attr = getattr(candidate, "text", None)
            if isinstance(text_attr, str) and text_attr.strip():
                return text_attr
    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        if isinstance(payload, Mapping):
            for key in ("text", "output_text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return ""


def _coerce_raw_output(response: Any) -> Mapping[str, Any] | None:
    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        else:
            if isinstance(payload, Mapping):
                return dict(payload)
    if isinstance(response, Mapping):
        return dict(response)
    return {"repr": repr(response)}


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
        self._generation_config: Mapping[str, Any] | None = dict(base_config) if base_config else None
        safety_settings = _prepare_safety_settings(config)
        self._safety_settings: Sequence[Mapping[str, Any]] | None = (
            list(safety_settings) if safety_settings else None
        )

    def generate(self, prompt: str) -> ProviderResponse:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        ts0 = time.time()
        response = _invoke_gemini(
            self._client,
            self._model,
            contents,
            self._generation_config,
            self._safety_settings,
        )
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
