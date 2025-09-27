"""HTTP client utilities for the Ollama provider."""

from __future__ import annotations

import importlib
import time
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Any, Protocol, TYPE_CHECKING, cast

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
from ..provider_spi import TokenUsage


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


requests: _RequestsModuleProtocol | None = None
Response: type[_ResponseProtocol]
requests_exceptions: _RequestsExceptionsProtocol


if TYPE_CHECKING:  # pragma: no cover - typing time placeholders
    import requests as _requests_mod  # type: ignore[import-untyped]  # noqa: F401
    from requests import Response as _RequestsResponse  # noqa: F401
    from requests import exceptions as _RequestsExceptions  # noqa: F401


def _initialize_requests() -> tuple[
    _RequestsModuleProtocol | None,
    type[_ResponseProtocol],
    _RequestsExceptionsProtocol,
]:
    try:
        _requests_module = importlib.import_module("requests")
    except ModuleNotFoundError:

        class _FallbackRequestsExceptions:  # pragma: no cover - trivial container
            class RequestException(Exception): ...

            class Timeout(RequestException): ...

            class HTTPError(RequestException):
                def __init__(self, message: str | None = None, response: Any | None = None):
                    super().__init__(message or "HTTP error")
                    self.response = response

        fallback_exceptions = cast(
            _RequestsExceptionsProtocol, _FallbackRequestsExceptions()
        )

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
                    raise cast(Any, fallback_exceptions.HTTPError)(response=self)

            def iter_lines(self) -> Iterable[bytes]:  # pragma: no cover - stub
                return []

        return (
            None,
            cast(type[_ResponseProtocol], _FallbackResponse),
            fallback_exceptions,
        )

    _typed_requests = cast(_RequestsModuleProtocol, _requests_module)
    response_type = cast(type[_ResponseProtocol], _requests_module.Response)
    exceptions = cast(_RequestsExceptionsProtocol, _requests_module.exceptions)
    return _typed_requests, response_type, exceptions


requests, Response, requests_exceptions = _initialize_requests()

DEFAULT_HOST = "http://127.0.0.1:11434"
__all__ = [
    "DEFAULT_HOST",
    "OllamaClient",
    "Response",
    "requests",
    "requests_exceptions",
]


def _combine_host(base: str, path: str) -> str:
    if base.endswith("/"):
        base = base[:-1]
    return f"{base}{path}"


def _token_usage_from_payload(payload: Mapping[str, Any]) -> TokenUsage:
    prompt_tokens = int(payload.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(payload.get("eval_count", 0) or 0)
    return TokenUsage(prompt=prompt_tokens, completion=completion_tokens)


class OllamaClient:
    """Lightweight HTTP client to talk with the Ollama API."""

    def __init__(
        self,
        host: str,
        *,
        session: _SessionProtocol | None = None,
        timeout: float = 60.0,
        pull_timeout: float = 300.0,
        auto_pull: bool = True,
    ) -> None:
        if session is None:
            if requests is None:  # pragma: no cover - defensive branch
                raise ImportError("requests is required unless a session is provided")
            session = requests.Session()
        self._session = session
        self._host = host
        self._timeout = timeout
        self._pull_timeout = pull_timeout
        self._auto_pull = auto_pull
        self._ready_models: set[str] = set()

    @property
    def host(self) -> str:
        return self._host

    def ensure_model(self, model_name: str) -> None:
        if model_name in self._ready_models:
            return

        show_response = self._request("/api/show", {"model": model_name})
        if show_response.status_code == 200:
            self._ready_models.add(model_name)
            show_response.close()
            return
        show_response.close()

        if not self._auto_pull:
            raise RetriableError(f"ollama model not available: {model_name}")

        with self._request(
            "/api/pull",
            {"model": model_name},
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
            for _ in pull_response.iter_lines():  # pragma: no cover - network interaction
                pass

        for _ in range(10):
            show_after = self._request("/api/show", {"model": model_name})
            if show_after.status_code == 200:
                self._ready_models.add(model_name)
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {model_name}")

    def chat(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_override: float | None = None,
    ) -> tuple[Mapping[str, Any], int, TokenUsage]:
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

            payload_json = cast(Mapping[str, Any], response.json())
        except ValueError as exc:
            raise RetriableError("invalid JSON from Ollama") from exc
        finally:
            response.close()

        latency_ms = int((time.time() - ts0) * 1000)
        usage = _token_usage_from_payload(payload_json)
        return payload_json, latency_ms, usage

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


__all__ += [
    "_SessionProtocol",
    "_ResponseProtocol",
    "_RequestsExceptionsProtocol",
    "_RequestsModuleProtocol",
    "_token_usage_from_payload",
    "_combine_host",
]
