from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Any, cast

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
from ._requests_compat import requests_exceptions, ResponseProtocol, SessionProtocol

_streaming_error_candidates: list[type[BaseException]] = []
_requests_exceptions_any = cast(Any, requests_exceptions)

try:
    _candidate = _requests_exceptions_any.ChunkedEncodingError
except AttributeError:
    pass
else:
    if isinstance(_candidate, type) and issubclass(_candidate, BaseException):
        _streaming_error_candidates.append(_candidate)

try:
    _candidate = _requests_exceptions_any.ProtocolError
except AttributeError:
    pass
else:
    if isinstance(_candidate, type) and issubclass(_candidate, BaseException):
        _streaming_error_candidates.append(_candidate)

if _streaming_error_candidates:
    _STREAMING_ERRORS: tuple[type[BaseException], ...] = tuple(_streaming_error_candidates)
else:
    _STREAMING_ERRORS = (requests_exceptions.RequestException,)


class _StreamingResponseWrapper:
    __slots__ = ("_response", "_path")

    def __init__(self, response: ResponseProtocol, path: str) -> None:
        self._response = response
        self._path = path

    def close(self) -> None:
        self._response.close()

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @status_code.setter
    def status_code(self, value: int) -> None:
        self._response.status_code = value

    @property
    def closed(self) -> bool:
        if hasattr(self._response, "closed"):
            return bool(self._response.closed)
        return False

    def json(self) -> Any:
        return self._response.json()

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_lines(self) -> Iterable[bytes]:
        try:
            yield from self._response.iter_lines()
        except _STREAMING_ERRORS as exc:
            self.close()
            raise RetriableError(
                f"Ollama streaming failed: {self._path}"
            ) from exc

    def __enter__(self) -> _StreamingResponseWrapper:
        self._response.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return self._response.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


def _combine_host(base: str, path: str) -> str:
    return f"{base[:-1] if base.endswith('/') else base}{path}"


class OllamaClient:
    __slots__ = ("_host", "_session", "_timeout", "_pull_timeout")

    def __init__(
        self,
        *,
        host: str,
        session: SessionProtocol,
        timeout: float,
        pull_timeout: float,
    ) -> None:
        self._host = host
        self._session = session
        self._timeout = timeout
        self._pull_timeout = pull_timeout

    def show(self, payload: Mapping[str, object]) -> ResponseProtocol:
        return self._post("/api/show", payload)

    def pull(self, payload: Mapping[str, object]) -> ResponseProtocol:
        response = self._ensure_success(
            "/api/pull",
            self._post("/api/pull", payload, stream=True, timeout=self._pull_timeout),
        )
        return _StreamingResponseWrapper(response, "/api/pull")

    def chat(
        self,
        payload: Mapping[str, object],
        *,
        timeout: float | None = None,
        stream: bool = False,
    ) -> ResponseProtocol:
        stream_flag = bool(payload.get("stream")) if stream is None else bool(stream)
        return self._ensure_success(
            "/api/chat",
            self._post("/api/chat", payload, stream=stream, timeout=timeout),
        )

    def _post(
        self,
        path: str,
        payload: Mapping[str, object],
        *,
        stream: bool = False,
        timeout: float | None = None,
    ) -> ResponseProtocol:
        url = _combine_host(self._host, path)
        try:
            return self._session.post(
                url,
                json=payload,
                stream=stream,
                timeout=timeout or self._timeout,
            )
        except requests_exceptions.Timeout as exc:  # pragma: no cover - passthrough
            raise TimeoutError(f"Ollama request timed out: {url}") from exc
        except requests_exceptions.RequestException as exc:  # pragma: no cover - passthrough
            raise RetriableError(f"Ollama request failed: {url}") from exc

    def _ensure_success(self, path: str, response: ResponseProtocol) -> ResponseProtocol:
        try:
            response.raise_for_status()
        except requests_exceptions.HTTPError as exc:
            response.close()
            self._raise_http_error(path, response.status_code, exc)
        return response

    @staticmethod
    def _raise_http_error(path: str, status: int, exc: Exception) -> None:
        message = f"Ollama request failed ({status}): {path}"
        if status in {401, 403}:
            raise AuthError(message) from exc
        if status == 429:
            raise RateLimitError(message) from exc
        if status in {408, 504}:
            raise TimeoutError(message) from exc
        raise RetriableError(message) from exc


__all__ = ["OllamaClient"]
