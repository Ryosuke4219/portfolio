"""OpenAI プロバイダ実装。"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, MutableMapping
from typing import Any

from ..config import ProviderConfig
from . import BaseProvider, ProviderResponse
from .openai_utils import (
    OpenAIClientFactory,
    build_chat_messages,
    build_system_user_contents,
    coerce_raw_output,
    determine_modes,
    extract_text_from_response,
    extract_usage_tokens,
)

__all__ = ["OpenAIProvider"]

try:  # pragma: no cover - OpenAI SDK が存在しない環境では読み込まれない
    import openai as _openai  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - 依存が無い環境ではプロバイダを登録しない
    _openai = None  # type: ignore[assignment]


def _resolve_api_key(env_name: str | None) -> str:
    if not env_name:
        raise RuntimeError(
            "OpenAI プロバイダを利用するには auth_env に API キーの環境変数を指定してください"
        )
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(
            f"Environment variable {env_name!r} is not set. OpenAI API キーを設定してください。"
        )
    return value


def _coerce_mapping(value: Any) -> MutableMapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _is_rate_limit_error(exc: Exception) -> bool:
    rate_limit_cls = getattr(_openai, "RateLimitError", None)
    if rate_limit_cls is not None and isinstance(exc, rate_limit_cls):
        return True
    return exc.__class__.__name__ == "RateLimitError"


def _split_endpoint(value: str | None) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    stripped = value.strip()
    if not stripped:
        return None, None
    lowered = stripped.lower()
    if lowered in {"responses", "chat_completions", "completions"}:
        return lowered, None
    return None, stripped


def _prepare_common_kwargs(config: ProviderConfig) -> MutableMapping[str, Any]:
    kwargs: MutableMapping[str, Any] = {}
    if config.temperature:
        kwargs["temperature"] = float(config.temperature)
    if config.top_p and config.top_p < 1.0:
        kwargs["top_p"] = float(config.top_p)
    extra = config.raw.get("request_kwargs")
    kwargs.update(_coerce_mapping(extra))
    return kwargs


class OpenAIProvider(BaseProvider):
    """OpenAI API を利用したプロバイダ実装。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if _openai is None:  # pragma: no cover - 依存未導入
            raise ImportError("openai パッケージがインストールされていません")
        api_key = _resolve_api_key(config.auth_env)
        self._model = config.model
        self._system_prompt = None
        raw_system_prompt = config.raw.get("system_prompt")
        if isinstance(raw_system_prompt, str):
            self._system_prompt = raw_system_prompt
        endpoint_mode, endpoint_url = _split_endpoint(config.endpoint)
        self._endpoint_url = endpoint_url
        self._preferred_modes: tuple[str, ...] = determine_modes(config, endpoint_mode)
        base_kwargs = _prepare_common_kwargs(config)
        self._request_kwargs = dict(base_kwargs)
        response_format = config.raw.get("response_format")
        self._response_format = (
            dict(response_format) if isinstance(response_format, Mapping) else None
        )
        default_headers = _coerce_mapping(config.raw.get("default_headers"))
        factory = OpenAIClientFactory(_openai)
        self._client = factory.create(api_key, config, self._endpoint_url, default_headers)

    def generate(self, prompt: str) -> ProviderResponse:
        last_error: Exception | None = None
        for mode in self._preferred_modes:
            try:
                response = self._invoke_mode(mode, prompt)
                if response is None:
                    continue
                break
            except Exception as exc:  # pragma: no cover - 実行時エラーを保持して次のモードへ
                if _is_rate_limit_error(exc):
                    raise RuntimeError(
                        "OpenAI quota exceeded. ダッシュボードで請求/使用量を確認。"
                    ) from exc
                last_error = exc
        else:
            if last_error:
                raise last_error
            raise RuntimeError("OpenAI API 呼び出しに使用可能なモードが見つかりませんでした")
        # response 取得後に計測しても間に合わないので invoke 内で測定する
        # 上記ループでは response は (結果, latency_ms) のタプルを想定
        result_obj, latency_ms = response
        output_text = extract_text_from_response(result_obj)
        prompt_tokens, completion_tokens = extract_usage_tokens(result_obj, prompt, output_text)
        raw_output = coerce_raw_output(result_obj)
        return ProviderResponse(
            output_text=output_text,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            latency_ms=latency_ms,
            raw_output=dict(raw_output) if isinstance(raw_output, Mapping) else None,
        )

    def _invoke_mode(self, mode: str, prompt: str) -> tuple[Any, int] | None:
        if mode == "responses":
            return self._call_responses(prompt)
        if mode == "chat_completions":
            return self._call_chat_completions(prompt)
        if mode == "completions":
            return self._call_completions(prompt)
        return None

    def _call_responses(self, prompt: str) -> tuple[Any, int] | None:
        try:
            create = self._client.responses.create
        except AttributeError:
            return None
        if not callable(create):
            return None
        kwargs = dict(self._request_kwargs)
        if self.config.max_tokens:
            kwargs.setdefault("max_output_tokens", int(self.config.max_tokens))
        if self._response_format:
            kwargs.setdefault("response_format", dict(self._response_format))
        contents = build_system_user_contents(self._system_prompt, prompt)
        ts0 = time.time()
        result = create(model=self._model, input=contents, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _call_chat_completions(self, prompt: str) -> tuple[Any, int] | None:
        try:
            create = self._client.chat.completions.create
        except AttributeError:
            create = None
        if not callable(create):
            # v0 互換
            try:
                create = self._client.ChatCompletion.create
            except AttributeError:
                create = None
        if not callable(create):
            return None
        kwargs = dict(self._request_kwargs)
        if self.config.max_tokens:
            kwargs.setdefault("max_tokens", int(self.config.max_tokens))
        if self._response_format and "response_format" not in kwargs:
            kwargs["response_format"] = dict(self._response_format)
        messages = build_chat_messages(self._system_prompt, prompt)
        ts0 = time.time()
        result = create(model=self._model, messages=messages, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _call_completions(self, prompt: str) -> tuple[Any, int] | None:
        # v0 系の text-davinci シリーズ向けエンドポイント
        try:
            create = self._client.completions.create
        except AttributeError:
            create = None
        if not callable(create):
            try:
                create = self._client.Completion.create
            except AttributeError:
                create = None
        if not callable(create):
            return None
        kwargs = dict(self._request_kwargs)
        if self.config.max_tokens:
            kwargs.setdefault("max_tokens", int(self.config.max_tokens))
        prompt_text = prompt
        if self._system_prompt:
            prompt_text = (
                f"{self._system_prompt}\n\n{prompt}" if prompt else self._system_prompt
            )
        ts0 = time.time()
        result = create(model=self._model, prompt=prompt_text, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

