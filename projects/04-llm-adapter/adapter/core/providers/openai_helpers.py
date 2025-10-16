from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
import os
import time
from typing import Any, Protocol

from ..config import ProviderConfig
from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest
from .openai_utils import build_chat_messages, build_responses_input

__all__ = [
    "ModeStrategy",
    "build_mode_strategies",
    "coerce_mapping",
    "normalize_openai_exception",
    "prepare_common_kwargs",
    "resolve_api_key",
]


class ModeStrategy(Protocol):
    def call(self, request: ProviderRequest) -> tuple[Any, int] | None: ...


def resolve_api_key(env_name: str | None) -> str:
    if not env_name:
        raise AuthError(
            "OpenAI プロバイダを利用するには auth_env に API キーの環境変数を指定してください",
        )
    value = os.getenv(env_name)
    if not value:
        raise AuthError(
            f"Environment variable {env_name!r} is not set. OpenAI API キーを設定してください。",
        )
    return value


def coerce_mapping(value: Any) -> MutableMapping[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def prepare_common_kwargs(config: ProviderConfig) -> MutableMapping[str, Any]:
    kwargs: MutableMapping[str, Any] = {}
    if config.temperature:
        kwargs["temperature"] = float(config.temperature)
    if config.top_p and config.top_p < 1.0:
        kwargs["top_p"] = float(config.top_p)
    kwargs.update(coerce_mapping(config.raw.get("request_kwargs")))
    return kwargs


def normalize_openai_exception(exc: Exception, sdk_module: Any | None) -> Exception:
    if _is_auth_error(exc):
        return AuthError("OpenAI API 認証に失敗しました")
    if _is_rate_limit_error(exc, sdk_module) or getattr(exc, "status_code", None) == 429:
        return RateLimitError("OpenAI のレート制限に達しました")
    if _is_timeout_error(exc):
        return TimeoutError("OpenAI API 呼び出しがタイムアウトしました")
    if _is_transient_error(exc):
        return RetriableError("OpenAI API が一時的に利用できません")
    return RetriableError("OpenAI API 呼び出しに失敗しました")


def build_mode_strategies(
    client: Any,
    config: ProviderConfig,
    system_prompt: str | None,
    response_format: Mapping[str, Any] | None,
    prepare_request_kwargs: Callable[[ProviderRequest], MutableMapping[str, Any]],
    unwrap_stream: Callable[[Any], Any],
) -> dict[str, ModeStrategy]:
    return {
        "responses": _ResponsesStrategy(
            client, config, system_prompt, response_format, prepare_request_kwargs, unwrap_stream
        ),
        "chat_completions": _ChatCompletionsStrategy(
            client, config, system_prompt, response_format, prepare_request_kwargs, unwrap_stream
        ),
        "completions": _CompletionsStrategy(
            client, config, system_prompt, prepare_request_kwargs, unwrap_stream
        ),
    }


def _is_rate_limit_error(exc: Exception, sdk_module: Any | None) -> bool:
    if sdk_module is None:
        return exc.__class__.__name__ == "RateLimitError"
    try:
        rate_limit_cls = sdk_module.RateLimitError
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
    if name in {"APIConnectionError", "InternalServerError", "ServiceUnavailableError", "TryAgain"}:
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and 500 <= status_code < 600


class _BaseModeStrategy:
    _create_paths: tuple[tuple[str, ...], ...] = ()

    def __init__(
        self,
        client: Any,
        config: ProviderConfig,
        system_prompt: str | None,
        prepare_request_kwargs: Callable[[ProviderRequest], MutableMapping[str, Any]],
        unwrap_stream: Callable[[Any], Any],
    ) -> None:
        self._client = client
        self._config = config
        self._system_prompt = system_prompt
        self._prepare_request_kwargs = prepare_request_kwargs
        self._unwrap_stream = unwrap_stream

    def call(self, request: ProviderRequest) -> tuple[Any, int] | None:
        create = self._resolve_create()
        if create is None:
            return None
        kwargs = self._prepare_request_kwargs(request)
        stream = bool(kwargs.get("stream"))
        self._apply_kwargs(request, kwargs)
        payload = self._build_payload(request, kwargs)
        started = time.time()
        result = create(**payload)
        latency_ms = int((time.time() - started) * 1000)
        if stream:
            result = self._unwrap_stream(result)
        return result, latency_ms

    def _resolve_create(self) -> Callable[..., Any] | None:
        for path in self._create_paths:
            target: Any | None = self._client
            for attr in path:
                target = getattr(target, attr, None)
                if target is None:
                    break
            if callable(target):
                return target
        return None

    def _apply_kwargs(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> None:
        return None

    def _build_payload(
        self,
        request: ProviderRequest,
        kwargs: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        raise NotImplementedError


class _ResponsesStrategy(_BaseModeStrategy):
    _create_paths = (("responses", "create"),)

    def __init__(
        self,
        client: Any,
        config: ProviderConfig,
        system_prompt: str | None,
        response_format: Mapping[str, Any] | None,
        prepare_request_kwargs: Callable[[ProviderRequest], MutableMapping[str, Any]],
        unwrap_stream: Callable[[Any], Any],
    ) -> None:
        super().__init__(client, config, system_prompt, prepare_request_kwargs, unwrap_stream)
        self._response_format = response_format

    def _apply_kwargs(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> None:
        max_tokens = request.max_tokens if request.max_tokens is not None else self._config.max_tokens
        if max_tokens:
            kwargs.setdefault("max_output_tokens", int(max_tokens))
        if self._response_format:
            kwargs.setdefault("response_format", dict(self._response_format))

    def _build_payload(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        payload: MutableMapping[str, Any] = {
            "model": request.model,
            "input": build_responses_input(self._system_prompt, request.messages, request.prompt),
        }
        payload.update(kwargs)
        return payload


class _ChatCompletionsStrategy(_BaseModeStrategy):
    _create_paths = (("chat", "completions", "create"), ("ChatCompletion", "create"))

    def __init__(
        self,
        client: Any,
        config: ProviderConfig,
        system_prompt: str | None,
        response_format: Mapping[str, Any] | None,
        prepare_request_kwargs: Callable[[ProviderRequest], MutableMapping[str, Any]],
        unwrap_stream: Callable[[Any], Any],
    ) -> None:
        super().__init__(client, config, system_prompt, prepare_request_kwargs, unwrap_stream)
        self._response_format = response_format

    def _apply_kwargs(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> None:
        max_tokens = request.max_tokens if request.max_tokens is not None else self._config.max_tokens
        if max_tokens:
            kwargs.setdefault("max_tokens", int(max_tokens))
        if self._response_format and "response_format" not in kwargs:
            kwargs["response_format"] = dict(self._response_format)

    def _build_payload(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        payload: MutableMapping[str, Any] = {
            "model": request.model,
            "messages": list(request.messages or build_chat_messages(self._system_prompt, request.prompt)),
        }
        payload.update(kwargs)
        return payload


class _CompletionsStrategy(_BaseModeStrategy):
    _create_paths = (("completions", "create"), ("Completion", "create"))

    def _apply_kwargs(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> None:
        max_tokens = request.max_tokens if request.max_tokens is not None else self._config.max_tokens
        if max_tokens:
            kwargs.setdefault("max_tokens", int(max_tokens))

    def _build_payload(self, request: ProviderRequest, kwargs: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        prompt_text = request.prompt
        if self._system_prompt:
            prompt_text = f"{self._system_prompt}\n\n{request.prompt}" if request.prompt else self._system_prompt
        payload: MutableMapping[str, Any] = {"model": request.model, "prompt": prompt_text}
        payload.update(kwargs)
        return payload
