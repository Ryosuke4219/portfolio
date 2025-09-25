"""OpenAI プロバイダ実装。"""

from __future__ import annotations

import os
import time
from typing import Any, Mapping, MutableMapping, Sequence

from ..config import ProviderConfig
from . import BaseProvider, ProviderResponse

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


def _build_system_user_contents(system_prompt: str | None, user_prompt: str) -> list[Mapping[str, Any]]:
    contents: list[Mapping[str, Any]] = []
    if system_prompt:
        contents.append(
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}],
            }
        )
    contents.append({"role": "user", "content": [{"type": "text", "text": user_prompt}]})
    return contents


def _build_chat_messages(system_prompt: str | None, user_prompt: str) -> list[Mapping[str, Any]]:
    messages: list[Mapping[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _extract_text_from_response(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    choices = getattr(response, "choices", None)
    if isinstance(choices, Sequence) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, Sequence):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, Mapping):
                            text_part = item.get("text")
                            if isinstance(text_part, str):
                                parts.append(text_part)
                    if parts:
                        return "".join(parts)
            text_value = first.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value
        message_attr = getattr(first, "message", None)
        if isinstance(message_attr, Mapping):
            content_attr = message_attr.get("content")
            if isinstance(content_attr, str) and content_attr.strip():
                return content_attr
        text_attr = getattr(first, "text", None)
        if isinstance(text_attr, str) and text_attr.strip():
            return text_attr
    output = getattr(response, "output", None)
    if isinstance(output, Sequence):
        parts: list[str] = []
        for item in output:
            if isinstance(item, Mapping):
                content = item.get("content")
                if isinstance(content, Sequence):
                    for fragment in content:
                        if isinstance(fragment, Mapping):
                            text_part = fragment.get("text")
                            if isinstance(text_part, str):
                                parts.append(text_part)
                elif isinstance(content, str):
                    parts.append(content)
        if parts:
            return "".join(parts)
    if hasattr(response, "model_dump"):
        try:
            dumped = response.model_dump()
        except Exception:  # pragma: no cover - defensive
            dumped = None
        if isinstance(dumped, Mapping):
            for key in ("output_text", "text"):
                value = dumped.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            choices = dumped.get("choices")
            if isinstance(choices, Sequence) and choices:
                first = choices[0]
                if isinstance(first, Mapping):
                    for path in (("message", "content"), ("text",)):
                        cursor: Any = first
                        for segment in path:
                            if isinstance(cursor, Mapping):
                                cursor = cursor.get(segment)
                            else:
                                cursor = None
                                break
                        if isinstance(cursor, str) and cursor.strip():
                            return cursor
    return ""


def _extract_usage_tokens(response: Any, prompt: str, output_text: str) -> tuple[int, int]:
    prompt_tokens = 0
    completion_tokens = 0
    usage = getattr(response, "usage", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        if prompt_tokens <= 0:
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        if completion_tokens <= 0:
            completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    if prompt_tokens <= 0 or completion_tokens <= 0:
        if isinstance(usage, Mapping):
            prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or prompt_tokens)
            completion_tokens = int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or completion_tokens
            )
    if prompt_tokens <= 0 or completion_tokens <= 0:
        if hasattr(response, "model_dump"):
            try:
                payload = response.model_dump()
            except Exception:  # pragma: no cover - defensive
                payload = None
            if isinstance(payload, Mapping):
                usage_dict = payload.get("usage")
                if isinstance(usage_dict, Mapping):
                    prompt_tokens = int(
                        usage_dict.get("prompt_tokens", usage_dict.get("input_tokens", prompt_tokens)) or prompt_tokens
                    )
                    completion_tokens = int(
                        usage_dict.get("completion_tokens", usage_dict.get("output_tokens", completion_tokens))
                        or completion_tokens
                    )
    if prompt_tokens <= 0:
        prompt_tokens = max(1, len(prompt.split()))
    if completion_tokens <= 0:
        tokens = len(output_text.split())
        completion_tokens = max(1, tokens) if tokens else 0
    return prompt_tokens, completion_tokens


def _coerce_raw_output(response: Any) -> Mapping[str, Any] | None:
    if hasattr(response, "model_dump"):
        try:
            payload = response.model_dump()
        except Exception:  # pragma: no cover - defensive
            payload = None
        else:
            if isinstance(payload, Mapping):
                return dict(payload)
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


class OpenAIProvider(BaseProvider):
    """OpenAI API を利用したプロバイダ実装。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if _openai is None:  # pragma: no cover - 依存未導入
            raise ImportError("openai パッケージがインストールされていません")
        api_key = _resolve_api_key(config.auth_env)
        self._model = config.model
        self._system_prompt = config.raw.get("system_prompt") if isinstance(config.raw.get("system_prompt"), str) else None
        endpoint_mode, endpoint_url = _split_endpoint(config.endpoint)
        self._endpoint_url = endpoint_url
        self._preferred_modes: tuple[str, ...] = self._determine_modes(config, endpoint_mode)
        base_kwargs = _prepare_common_kwargs(config)
        self._request_kwargs = dict(base_kwargs)
        response_format = config.raw.get("response_format")
        self._response_format = dict(response_format) if isinstance(response_format, Mapping) else None
        self._client = self._create_client(api_key, config)

    def _determine_modes(self, config: ProviderConfig, endpoint_mode: str | None) -> tuple[str, ...]:
        preferred = config.raw.get("api")
        modes: list[str] = []
        if isinstance(preferred, str) and preferred.strip():
            modes.append(preferred.strip().lower())
        if endpoint_mode:
            modes.append(endpoint_mode)
        modes.extend(["responses", "chat_completions", "completions"])
        # 順序は維持しつつ重複を排除
        seen: set[str] = set()
        ordered: list[str] = []
        for mode in modes:
            if mode not in {"responses", "chat_completions", "completions"}:
                continue
            if mode in seen:
                continue
            seen.add(mode)
            ordered.append(mode)
        return tuple(ordered)

    def _create_client(self, api_key: str, config: ProviderConfig) -> Any:
        endpoint = self._endpoint_url
        organization = config.raw.get("organization") if isinstance(config.raw.get("organization"), str) else None
        default_headers = _coerce_mapping(config.raw.get("default_headers"))
        if hasattr(_openai, "OpenAI"):
            kwargs: dict[str, Any] = {"api_key": api_key}
            if endpoint:
                kwargs["base_url"] = endpoint
            if organization:
                kwargs["organization"] = organization
            if default_headers:
                kwargs["default_headers"] = dict(default_headers)
            return _openai.OpenAI(**kwargs)
        # v0 系 SDK 互換
        _openai.api_key = api_key  # type: ignore[attr-defined]
        if endpoint:
            setattr(_openai, "base_url", endpoint)
        if organization:
            setattr(_openai, "organization", organization)
        for key, value in default_headers.items():
            # API v0 では default_headers が無いため、ベースとなるヘッダ辞書を用意
            headers = getattr(_openai, "_default_headers", {})
            headers[key] = value
            setattr(_openai, "_default_headers", headers)
        return _openai

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
        output_text = _extract_text_from_response(result_obj)
        prompt_tokens, completion_tokens = _extract_usage_tokens(result_obj, prompt, output_text)
        raw_output = _coerce_raw_output(result_obj)
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
        responses_api = getattr(self._client, "responses", None)
        create = getattr(responses_api, "create", None)
        if not callable(create):
            return None
        kwargs = dict(self._request_kwargs)
        if self.config.max_tokens:
            kwargs.setdefault("max_output_tokens", int(self.config.max_tokens))
        if self._response_format:
            kwargs.setdefault("response_format", dict(self._response_format))
        contents = _build_system_user_contents(self._system_prompt, prompt)
        ts0 = time.time()
        result = create(model=self._model, input=contents, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _call_chat_completions(self, prompt: str) -> tuple[Any, int] | None:
        chat_api = getattr(getattr(self._client, "chat", None), "completions", None)
        create = getattr(chat_api, "create", None)
        if not callable(create):
            # v0 互換
            create = getattr(self._client, "ChatCompletion", None)
            if create and hasattr(create, "create"):
                create = getattr(create, "create")
        if not callable(create):
            return None
        kwargs = dict(self._request_kwargs)
        if self.config.max_tokens:
            kwargs.setdefault("max_tokens", int(self.config.max_tokens))
        if self._response_format and "response_format" not in kwargs:
            kwargs["response_format"] = dict(self._response_format)
        messages = _build_chat_messages(self._system_prompt, prompt)
        ts0 = time.time()
        result = create(model=self._model, messages=messages, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

    def _call_completions(self, prompt: str) -> tuple[Any, int] | None:
        # v0 系の text-davinci シリーズ向けエンドポイント
        create = getattr(self._client, "Completion", None)
        if create and hasattr(create, "create"):
            create = getattr(create, "create")
        if not callable(create):
            completions_api = getattr(self._client, "completions", None)
            create = getattr(completions_api, "create", None)
        if not callable(create):
            return None
        kwargs = dict(self._request_kwargs)
        if self.config.max_tokens:
            kwargs.setdefault("max_tokens", int(self.config.max_tokens))
        prompt_text = prompt
        if self._system_prompt:
            prompt_text = f"{self._system_prompt}\n\n{prompt}" if prompt else self._system_prompt
        ts0 = time.time()
        result = create(model=self._model, prompt=prompt_text, **kwargs)
        latency_ms = int((time.time() - ts0) * 1000)
        return result, latency_ms

