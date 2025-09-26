"""Ollama provider with automatic model management."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, cast

from ..errors import AuthError, ConfigError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI, TokenUsage


class _ResponseProtocol(Protocol):
    status_code: int

    def close(self) -> None:
        ...

    def __enter__(self) -> _ResponseProtocol:
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        ...

    def json(self) -> Any:
        ...

    def raise_for_status(self) -> None:
        ...

    def iter_lines(self) -> Iterable[bytes]:
        ...


class _SessionProtocol(Protocol):
    def post(self, url: str, *args: Any, **kwargs: Any) -> _ResponseProtocol:
        ...


if TYPE_CHECKING:  # pragma: no cover - typing time placeholders
    requests: Any
    Response = _ResponseProtocol
    requests_exceptions: Any
else:  # pragma: no cover - allow running without the optional dependency
    import importlib

    try:
        _requests_module = importlib.import_module("requests")
    except ModuleNotFoundError:
        requests = None

        class _FallbackRequestsExceptions:  # pragma: no cover - trivial container
            class RequestException(Exception):
                pass

            class Timeout(RequestException):
                pass

            class HTTPError(RequestException):
                def __init__(self, message: str | None = None, response: Any | None = None):
                    super().__init__(message or "HTTP error")
                    self.response = response

        requests_exceptions = _FallbackRequestsExceptions()

        class Response:
            """Very small stub mimicking the subset of Response we rely on."""

            status_code: int

            def __init__(self, status_code: int = 200) -> None:
                self.status_code = status_code

            def close(self) -> None:  # pragma: no cover - trivial stub
                return None

            def __enter__(self) -> Response:  # pragma: no cover - stub
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
                    raise requests_exceptions.HTTPError(response=self)

            def iter_lines(self) -> Iterable[bytes]:  # pragma: no cover - stub
                return []
    else:
        requests = cast(Any, _requests_module)
        Response = cast(type[_ResponseProtocol], _requests_module.Response)
        requests_exceptions = cast(Any, _requests_module.exceptions)

DEFAULT_HOST = "http://127.0.0.1:11434"
__all__ = ["OllamaProvider", "DEFAULT_HOST"]


def _combine_host(base: str, path: str) -> str:
    if base.endswith("/"):
        base = base[:-1]
    return f"{base}{path}"


def _token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
    prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(payload.get("eval_count", 0) or 0)
    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


class OllamaProvider(ProviderSPI):
    """Provider backed by the local Ollama HTTP API."""

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
    ) -> None:
        self._model = model
        self._name = name or f"ollama:{model}"
        env_host = os.environ.get("OLLAMA_BASE_URL")
        if not env_host:
            env_host = os.environ.get("OLLAMA_HOST")
        self._host: str = host or env_host or DEFAULT_HOST
        if session is None:
            if requests is None:  # pragma: no cover - defensive branch
                raise ImportError("requests is required unless a session is provided")
            session = requests.Session()
        self._session = session
        self._timeout = timeout
        self._pull_timeout = pull_timeout
        self._auto_pull = auto_pull
        self._model_ready = False

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _request(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        stream: bool = False,
        timeout: float | None = None,
    ) -> _ResponseProtocol:
        url = _combine_host(self._host, path)
        try:
            response = self._session.post(
                url,
                json=payload,
                stream=stream,
                timeout=timeout or self._timeout,
            )
        except requests_exceptions.Timeout as exc:  # pragma: no cover - error handling
            raise TimeoutError(f"Ollama request timed out: {url}") from exc
        except requests_exceptions.RequestException as exc:  # pragma: no cover
            raise RetriableError(f"Ollama request failed: {url}") from exc
        return response

    def _ensure_model(self) -> None:
        if self._model_ready:
            return

        show_response = self._request("/api/show", {"model": self._model})
        if show_response.status_code == 200:
            self._model_ready = True
            show_response.close()
            return

        show_response.close()

        if not self._auto_pull:
            raise RetriableError(f"ollama model not available: {self._model}")

        with self._request(
            "/api/pull",
            {"model": self._model},
            stream=True,
            timeout=self._pull_timeout,
        ) as pull_response:
            try:
                pull_response.raise_for_status()
            except requests_exceptions.HTTPError as exc:
                status = pull_response.status_code
                if status in {401, 403}:
                    raise AuthError(str(exc)) from exc
                if status == 429:
                    raise RateLimitError(str(exc)) from exc
                if status in {408, 504}:
                    raise TimeoutError(str(exc)) from exc
                raise RetriableError(str(exc)) from exc
            # Drain the streaming response to complete the pull.
            for _ in pull_response.iter_lines():  # pragma: no cover - network interaction
                pass

        # Verify again with a short retry window.
        for _ in range(10):
            show_after = self._request("/api/show", {"model": self._model})
            if show_after.status_code == 200:
                self._model_ready = True
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {self._model}")

    # ------------------------------------------------------------------
    # ProviderSPI implementation
    # ------------------------------------------------------------------
    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self._ensure_model()

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": request.prompt,
                }
            ],
            "stream": False,
        }

        timeout_override: float | None = None
        if request.options and isinstance(request.options, Mapping):
            option_items = dict(request.options.items())
            timeout_keys = ("request_timeout_s", "REQUEST_TIMEOUT_S")
            for key in timeout_keys:
                if key in option_items:
                    raw_timeout = option_items.pop(key)
                    if raw_timeout is not None:
                        try:
                            timeout_override = float(raw_timeout)
                        except (TypeError, ValueError) as exc:
                            raise ConfigError(
                                "request_timeout_s must be a number"
                            ) from exc
                    break

            option_items.pop("prompt", None)
            payload.update(option_items)

        ts0 = time.time()
        response = self._request("/api/chat", payload, timeout=timeout_override)
        try:
            try:
                response.raise_for_status()
            except requests_exceptions.HTTPError as exc:
                status = response.status_code
                if status in {401, 403}:
                    raise AuthError(str(exc)) from exc
                if status == 429:
                    raise RateLimitError(str(exc)) from exc
                if status in {408, 504}:
                    raise TimeoutError(str(exc)) from exc
                if status >= 500:
                    raise RetriableError(str(exc)) from exc
                raise RetriableError(str(exc)) from exc

            payload_json = response.json()
        except ValueError as exc:
            raise RetriableError("invalid JSON from Ollama") from exc
        finally:
            response.close()

        message = payload_json.get("message")
        text = ""
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                text = content

        if not isinstance(text, str):
            text = ""

        latency_ms = int((time.time() - ts0) * 1000)
        usage = _token_usage_from_payload(payload_json)

        return ProviderResponse(text=text, token_usage=usage, latency_ms=latency_ms)
