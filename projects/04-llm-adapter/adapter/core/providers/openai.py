"""OpenAI プロバイダ実装。"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from ..config import ProviderConfig
from ..errors import AuthError, ProviderSkip, RateLimitError, TimeoutError
from ..provider_spi import ProviderRequest, TokenUsage
from . import BaseProvider, ProviderResponse
from .openai_helpers import (
    build_mode_strategies,
    coerce_mapping,
    ModeStrategy,
    normalize_openai_exception,
    prepare_common_kwargs,
    resolve_api_key,
)
from .openai_utils import (
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


class OpenAIProvider(BaseProvider):
    """OpenAI API を利用したプロバイダ実装。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if _openai is None:  # pragma: no cover - 依存未導入
            raise ImportError("openai パッケージがインストールされていません")
        api_key = resolve_api_key(config.auth_env)
        self._model = config.model
        self._system_prompt = None
        raw_system_prompt = config.raw.get("system_prompt")
        if isinstance(raw_system_prompt, str):
            self._system_prompt = raw_system_prompt
        endpoint_mode, endpoint_url = _split_endpoint(config.endpoint)
        self._endpoint_url = endpoint_url
        self._preferred_modes: tuple[str, ...] = determine_modes(config, endpoint_mode)
        base_kwargs = prepare_common_kwargs(config)
        self._request_kwargs = dict(base_kwargs)
        response_format = config.raw.get("response_format")
        self._response_format = (
            dict(response_format) if isinstance(response_format, Mapping) else None
        )
        default_headers = coerce_mapping(config.raw.get("default_headers"))
        factory = OpenAIClientFactory(_openai)
        self._client = factory.create(api_key, config, self._endpoint_url, default_headers)
        self._strategies: dict[str, ModeStrategy] = build_mode_strategies(
            self._client,
            self.config,
            self._system_prompt,
            self._response_format,
            self._prepare_request_kwargs,
            self._unwrap_stream_result,
        )

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
                normalized = normalize_openai_exception(exc, _openai)
                if isinstance(normalized, RateLimitError | AuthError | TimeoutError | ProviderSkip):
                    raise normalized from exc
                last_error = normalized
                last_cause = exc
        else:
            if last_error:
                raise last_error from last_cause
            raise ProviderSkip("OpenAI API 呼び出しに使用可能なモードが見つかりませんでした")
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
        strategy = self._strategies.get(mode)
        if strategy is not None:
            return strategy.call(request)
        return None

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

    def _unwrap_stream_result(self, response: Any) -> Any:
        getter = getattr(response, "get_final_response", None)
        if callable(getter):
            try:
                final = getter()
            except Exception:  # pragma: no cover - defensive fallback
                final = None
            if final is not None:
                return final
        final_response = getattr(response, "response", None)
        if final_response is not None:
            return final_response
        return response
