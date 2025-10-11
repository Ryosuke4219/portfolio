"""OpenAI プロバイダ実装。"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import os
import time
from typing import Any

from ..config import ProviderConfig
from ..errors import AuthError, ProviderSkip, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, TokenUsage
from . import BaseProvider, ProviderResponse
from .openai_utils import (
    build_chat_messages,
    build_responses_input,
    coerce_raw_output,
    determine_modes,
    extract_text_from_response,
    extract_usage_tokens,
    OpenAIClientFactory,
)

__all__ = ["OpenAIProvider"]

_openai: Any | None = None
try:  # pragma: no cover - OpenAI SDK が存在しない環境では読み込まれない
    import openai as _openai_module
except ModuleNotFoundError:  # pragma: no cover - 依存が無い環境ではプロバイダを登録しない
    pass
else:
    _openai = _openai_module


def _resolve_api_key(env_name: str | None) -> str:
    if not env_name:
        raise AuthError(
            "OpenAI プロバイダを利用するには auth_env に API キーの環境変数を指定してください"
        )
    value = os.getenv(env_name)
    if not value:
        raise AuthError(
            f"Environment variable {env_name!r} is not set. OpenAI API キーを設定してください。"
        )
    return value


def _coerce_mapping(value: Any) -> MutableMapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _is_rate_limit_error(exc: Exception) -> bool:
    if _openai is None:
        return exc.__class__.__name__ == "RateLimitError"
    try:
        rate_limit_cls = _openai.RateLimitError
    except AttributeError:
        return exc.__class__.__name__ == "RateLimitError"
    return isinstance(exc, rate_limit_cls)


def _is_timeout_error(exc: Exception) -> bool:
    name = exc.__class__.__name__
    if name in {"APITimeoutError", "Timeout"}:
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and status_code in {408, 504}


def _is_auth_error(exc: Exception) -> bool:
    name = exc.__class__.__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and status_code in {401, 403}


def _is_transient_error(exc: Exception) -> bool:
    name = exc.__class__.__name__
    transient_names = {
        "APIConnectionError",
        "InternalServerError",
        "ServiceUnavailableError",
        "TryAgain",
    }
    if name in transient_names:
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and 500 <= status_code < 600


def _normalize_openai_exception(exc: Exception) -> Exception:
    if _is_auth_error(exc):
        return AuthError("OpenAI API 認証に失敗しました")
    if _is_rate_limit_error(exc) or getattr(exc, "status_code", None) == 429:
        return RateLimitError("OpenAI のレート制限に達しました")
    if _is_timeout_error(exc):
        return TimeoutError("OpenAI API 呼び出しがタイムアウトしました")
    if _is_transient_error(exc):
        return RetriableError("OpenAI API が一時的に利用できません")
    return RetriableError("OpenAI API 呼び出しに失敗しました")


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

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        prompt = request.prompt
        last_error: Exception | None = None
        last_cause: Exception | None = None
        for mode in self._preferred_modes:
            try:
                response = self._invoke_mode(mode, request)
                if response is None:
                    continue
                break
            except Exception as exc:  # pragma: no cover - 実行時エラーを保持して次のモードへ
                normalized = _normalize_openai_exception(exc)
                if isinstance(
                    normalized, RateLimitError | AuthError | TimeoutError | ProviderSkip
                ):
                    raise normalized from exc
                last_error = normalized
                last_cause = exc
        else:
            if last_error:
                raise last_error from last_cause
            raise ProviderSkip("OpenAI API 呼び出しに使用可能なモードが見つかりませんでした")
        # response 取得後に計測しても間に合わないので invoke 内で測定する
        # 上記ループでは response は (結果, latency_ms) のタプルを想定
        result_obj, latency_ms = response
        output_text = extract_text_from_response(result_obj)
        prompt_tokens, completion_tokens = extract_usage_tokens(result_obj, prompt, output_text)
        raw_output = coerce_raw_output(result_obj)
        token_usage = TokenUsage(prompt=prompt_tokens, completion=completion_tokens)
        return ProviderResponse(
            text=output_text,
            latency_ms=latency_ms,
            token_usage=token_usage,
            model=request.model,
            raw=dict(raw_output) if isinstance(raw_output, Mapping) else None,
        )

    def _invoke_mode(self, mode: str, request: ProviderRequest) -> tuple[Any, int] | None:
        if mode == "responses":
            return self._call_responses(request)
        if mode == "chat_completions":
            return self._call_chat_completions(request)
        if mode == "completions":
            return self._call_completions(request)
        return None

    def _call_responses(self, request: ProviderRequest) -> tuple[Any, int] | None:
        try:
            create = self._client.responses.create
        except AttributeError:
            return None
        if not callable(create):
            return None
        kwargs = self._prepare_request_kwargs(request)
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        if max_tokens:
            kwargs.setdefault("max_output_tokens", int(max_tokens))
        if self._response_format:
            kwargs.setdefault("response_format", dict(self._response_format))
        contents = build_responses_input(self._system_prompt, request.messages, request.prompt)
        ts0 = time.time()
        result = create(model=request.model, input=contents, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _call_chat_completions(self, request: ProviderRequest) -> tuple[Any, int] | None:
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
        kwargs = self._prepare_request_kwargs(request)
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        if max_tokens:
            kwargs.setdefault("max_tokens", int(max_tokens))
        if self._response_format and "response_format" not in kwargs:
            kwargs["response_format"] = dict(self._response_format)
        messages = list(request.messages or build_chat_messages(self._system_prompt, request.prompt))
        ts0 = time.time()
        result = create(model=request.model, messages=messages, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _call_completions(self, request: ProviderRequest) -> tuple[Any, int] | None:
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
        kwargs = self._prepare_request_kwargs(request)
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        if max_tokens:
            kwargs.setdefault("max_tokens", int(max_tokens))
        prompt_text = request.prompt
        if self._system_prompt:
            prompt_text = (
                f"{self._system_prompt}\n\n{request.prompt}" if request.prompt else self._system_prompt
            )
        ts0 = time.time()
        result = create(model=request.model, prompt=prompt_text, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _prepare_request_kwargs(self, request: ProviderRequest) -> MutableMapping[str, Any]:
        kwargs: MutableMapping[str, Any] = dict(self._request_kwargs)
        options = request.options or {}
        for key, value in options.items():
            if isinstance(value, Mapping):
                kwargs[key] = dict(value)
            else:
                kwargs[key] = value
        if request.temperature is not None:
            kwargs["temperature"] = float(request.temperature)
        if request.top_p is not None:
            kwargs["top_p"] = float(request.top_p)
        if request.stop:
            kwargs["stop"] = tuple(request.stop)
        if request.timeout_s is not None:
            kwargs["timeout"] = float(request.timeout_s)
        return kwargs

