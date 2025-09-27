"""Ollama provider with automatic model management (single-file, client inlined)."""

from __future__ import annotations

import importlib
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, cast

from ..errors import AuthError, ConfigError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI, TokenUsage

__all__ = ["OllamaProvider", "DEFAULT_HOST"]

# ------------------------------------------------------------------------------
# Protocols for HTTP layer
# ------------------------------------------------------------------------------

class _ResponseProtocol(Protocol):
    status_code: int

    def close(self) -> None: ...
    def __enter__(self) -> _ResponseProtocol: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...
    def json(self) -> Any: ...
    def raise_for_status(self) -> None: ...
    def iter_lines(self) -> Iterable[bytes]: ...


class _SessionProtocol(Protocol):
    def post(self, url: str, *args: Any, **kwargs: Any) -> _ResponseProtocol: ...


class _RequestsExceptionsProtocol(Protocol):
    Timeout: type[Exception]
    RequestException: type[Exception]
    HTTPError: type[Exception]


class _RequestsModuleProtocol(Protocol):
    def Session(self) -> _SessionProtocol: ...
    exceptions: _RequestsExceptionsProtocol
    Response: type[_ResponseProtocol]


# ------------------------------------------------------------------------------
# requests import (with fallbacks when not installed)
# ------------------------------------------------------------------------------

RequestsModule: TypeAlias = _RequestsModuleProtocol | None
ResponseType: TypeAlias = type[_ResponseProtocol]
RequestsExceptions: TypeAlias = _RequestsExceptionsProtocol

if TYPE_CHECKING:  # pragma: no cover - hints only
    import requests as _requests_mod  # noqa: F401
    from requests import Response as _RequestsResponse  # noqa: F401
    from requests import exceptions as _RequestsExceptions  # noqa: F401


def _initialize_requests() -> tuple[RequestsModule, ResponseType, RequestsExceptions]:
    try:
        _requests_module = importlib.import_module("requests")
    except ModuleNotFoundError:
        # Fallback exceptions container
        class _FallbackRequestsExceptions:  # pragma: no cover - trivial container
            class RequestException(Exception): ...
            class Timeout(RequestException): ...
            class HTTPError(RequestException):
                def __init__(self, message: str | None = None, response: Any | None = None):
                    super().__init__(message or "HTTP error")
                    self.response = response

        fallback_exceptions = cast(_RequestsExceptionsProtocol, _FallbackRequestsExceptions())

        class _FallbackResponse:
            """Very small stub mimicking the subset of Response we rely on."""
            status_code: int

            def __init__(self, status_code: int = 200) -> None:
                self.status_code = status_code

            def close(self) -> None:  # pragma: no cover - trivial stub
                return None

            def __enter__(self) -> _FallbackResponse:  # pragma: no cover - stub
                return self

            def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
            ) -> bool | None:  # pragma: no cover - stub
                return None

            def json(self) -> Any:  # pragma: no cover - tests supply payloads
                return {}

            def raise_for_status(self) -> None:  # pragma: no cover - stub
                if self.status_code >= 400:
                    # cast to Any because nested class
                    raise cast(Any, fallback_exceptions.HTTPError)(response=self)

            def iter_lines(self) -> Iterable[bytes]:  # pragma: no cover - stub
                return []

        return (
            None,
            cast(ResponseType, _FallbackResponse),
            fallback_exceptions,
        )

    typed_requests = cast(_RequestsModuleProtocol, _requests_module)
    response_type = cast(ResponseType, _requests_module.Response)
    exceptions = cast(_RequestsExceptionsProtocol, _requests_module.exceptions)
    return typed_requests, response_type, exceptions


# Exported singletons (module-level) for easy monkeypatch in tests
requests, Response, requests_exceptions = _initialize_requests()

DEFAULT_HOST = "http://127.0.0.1:11434"


# ------------------------------------------------------------------------------
# Inlined OllamaClient (HTTP facade)
# ------------------------------------------------------------------------------

class OllamaClient:
    """HTTP facade for the Ollama API. Handles requests and model readiness."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        *,
        session: _SessionProtocol | None = None,
        timeout: float = 60.0,
        pull_timeout: float = 300.0,
        auto_pull: bool = True,
    ) -> None:
        self.host = host.rstrip("/") if host else DEFAULT_HOST
        if session is None:
            if requests is None:  # pragma: no cover - defensive
                raise ImportError("requests is required unless a session is provided")
            session = requests.Session()
        self._session = session
        self._timeout = float(timeout)
        self._pull_timeout = float(pull_timeout)
        self._auto_pull = bool(auto_pull)
        self._ready_models: set[str] = set()

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _combine_host(base: str, path: str) -> str:
        return f"{base}{path if path.startswith('/') else '/'+path}"

    @staticmethod
    def _token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
        prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(payload.get("eval_count", 0) or 0)
        return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)

    # -- HTTP primitives -------------------------------------------------------

    def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        stream: bool = False,
        timeout: float | None = None,
    ) -> _ResponseProtocol:
        url = self._combine_host(self.host, path)
        try:
            return self._session.post(
                url,
                json=payload,
                stream=stream,
                timeout=timeout or self._timeout,
            )
        except requests_exceptions.Timeout as exc:  # pragma: no cover - network error
            raise TimeoutError(f"Ollama request timed out: {url}") from exc
        except requests_exceptions.RequestException as exc:  # pragma: no cover
            raise RetriableError(f"Ollama request failed: {url}") from exc

    # -- model management ------------------------------------------------------

    def ensure_model(self, model_name: str) -> None:
        if model_name in self._ready_models:
            return

        show_resp = self._post("/api/show", {"model": model_name})
        if show_resp.status_code == 200:
            self._ready_models.add(model_name)
            show_resp.close()
            return
        show_resp.close()

        if not self._auto_pull:
            raise RetriableError(f"ollama model not available: {model_name}")

        # pull with streaming; just drain to complete
        with self._post(
            "/api/pull",
            {"model": model_name},
            stream=True,
            timeout=self._pull_timeout,
        ) as pull_resp:
            try:
                pull_resp.raise_for_status()
            except requests_exceptions.HTTPError as exc:
                status = pull_resp.status_code
                if status in {401, 403}:
                    raise AuthError(str(exc)) from exc
                if status == 429:
                    raise RateLimitError(str(exc)) from exc
                if status in {408, 504}:
                    raise TimeoutError(str(exc)) from exc
                raise RetriableError(str(exc)) from exc
            for _ in pull_resp.iter_lines():  # pragma: no cover - network I/O
                pass

        # verify availability with retries
        for _ in range(10):
            show_after = self._post("/api/show", {"model": model_name})
            if show_after.status_code == 200:
                self._ready_models.add(model_name)
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {model_name}")

    # -- chat endpoint ---------------------------------------------------------

    def chat(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_override: float | None = None,
    ) -> tuple[dict[str, Any], int, TokenUsage]:
        """Invoke /api/chat and return (json, latency_ms, token_usage)."""
        ts0 = time.time()
        resp = self._post("/api/chat", payload, timeout=timeout_override)
        try:
            try:
                resp.raise_for_status()
            except requests_exceptions.HTTPError as exc:
                status = resp.status_code
                if status in {401, 403}:
                    raise AuthError(str(exc)) from exc
                if status == 429:
                    raise RateLimitError(str(exc)) from exc
                if status in {408, 504}:
                    raise TimeoutError(str(exc)) from exc
                if status >= 500:
                    raise RetriableError(str(exc)) from exc
                raise RetriableError(str(exc)) from exc

            data = resp.json()
        except ValueError as exc:
            raise RetriableError("invalid JSON from Ollama") from exc
        finally:
            resp.close()

        latency_ms = int((time.time() - ts0) * 1000)
        usage = self._token_usage_from_payload(data)
        return cast(dict[str, Any], data), latency_ms, usage


# ------------------------------------------------------------------------------
# Provider (delegates HTTP to inlined OllamaClient)
# ------------------------------------------------------------------------------

class OllamaProvider(ProviderSPI):
    """Provider backed by the local Ollama HTTP API via inlined OllamaClient."""

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        host: str | None = None,
        session: _SessionProtocol | None = None,
        timeout: float = 60.0,
        pull_timeout: float = 300.0,
        auto_pull: bool = True,
        client: OllamaClient | None = None,
    ) -> None:
        # Factory/CLI で ``ProviderRequest.model`` に設定される推奨デフォルトを保持。
        self._model = model
        self._name = name or f"ollama:{model}"
        env_host = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
        resolved_host = host or env_host or DEFAULT_HOST

        self._client = client or OllamaClient(
            resolved_host,
            session=session,
            timeout=timeout,
            pull_timeout=pull_timeout,
            auto_pull=auto_pull,
        )

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    # ------------------------------------------------------------------
    # ProviderSPI implementation
    # ------------------------------------------------------------------
    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        model_name = request.model
        if not isinstance(model_name, str):
            raise ConfigError("OllamaProvider requires request.model to be set")
        model_name = model_name.strip()
        if not model_name:
            raise ConfigError("OllamaProvider requires request.model to be set")

        # Ensure model exists (pull if allowed)
        self._client.ensure_model(model_name)

        # ---- payload building -------------------------------------------------
        def _coerce_content(entry: Mapping[str, Any]) -> str:
            content = entry.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
                parts = [part for part in content if isinstance(part, str)]
                return "\n".join(parts)
            if content is None:
                return ""
            return str(content)

        messages_payload: list[dict[str, str]] = []
        for chat_message in request.chat_messages:
            if not isinstance(chat_message, Mapping):
                continue
            role = str(chat_message.get("role", "user")) or "user"
            text = _coerce_content(chat_message).strip()
            if text:
                messages_payload.append({"role": role, "content": text})

        if not messages_payload and request.prompt_text:
            messages_payload.append({"role": "user", "content": request.prompt_text})

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages_payload,
            "stream": False,
        }

        # --- options 統合（新SPI + 互換） ---
        options_payload: dict[str, Any] = {}
        if request.max_tokens is not None:
            options_payload["num_predict"] = int(request.max_tokens)
        if request.temperature is not None:
            options_payload["temperature"] = float(request.temperature)
        if request.top_p is not None:
            options_payload["top_p"] = float(request.top_p)
        if request.stop:
            options_payload["stop"] = list(request.stop)

        # timeout の優先度: request.timeout_s > options.request_timeout_s > default
        timeout_override: float | None = None
        if request.timeout_s is not None:
            timeout_override = float(request.timeout_s)

        if request.options and isinstance(request.options, Mapping):
            opt_items = dict(request.options.items())

            # timeout 上書き (options 側)
            for key in ("request_timeout_s", "REQUEST_TIMEOUT_S"):
                if key in opt_items:
                    raw_timeout = opt_items.pop(key)
                    if raw_timeout is not None and timeout_override is None:
                        try:
                            timeout_override = float(raw_timeout)
                        except (TypeError, ValueError) as exc:
                            raise ConfigError("request_timeout_s must be a number") from exc
                    break

            # 衝突しうるトップレベルは除去
            for k in ("model", "messages", "prompt"):
                opt_items.pop(k, None)

            # ネストした options をマージ
            nested_opts = opt_items.pop("options", None)
            if isinstance(nested_opts, Mapping):
                options_payload.update(dict(nested_opts))

            # 残りはトップレベルに反映（Ollamaが理解する追加パラメータ）
            for k, v in opt_items.items():
                payload[k] = v

        if options_payload:
            payload["options"] = {**options_payload, **payload.get("options", {})}

        # ---- HTTP call --------------------------------------------------------
        payload_json, latency_ms, usage = self._client.chat(
            payload,
            timeout_override=timeout_override,
        )

        # ---- response shaping -------------------------------------------------
        message = payload_json.get("message")
        text = ""
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                text = content
        if not isinstance(text, str):
            text = ""

        return ProviderResponse(
            text=text,
            token_usage=usage,
            latency_ms=latency_ms,
            model=model_name,
            finish_reason=payload_json.get("done_reason"),
            raw=payload_json,
        )
