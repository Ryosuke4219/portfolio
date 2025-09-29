"""Compat utilities for optional ``requests`` dependency."""
from __future__ import annotations

from collections.abc import Iterable
import importlib
from types import TracebackType
import typing
from typing import Any, cast, Protocol


class ResponseProtocol(Protocol):
    status_code: int

    def close(self) -> None: ...
    def __enter__(self) -> ResponseProtocol: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...
    def json(self) -> Any: ...
    def raise_for_status(self) -> None: ...
    def iter_lines(self) -> Iterable[bytes]: ...


class SessionProtocol(Protocol):
    def post(self, url: str, *args: Any, **kwargs: Any) -> ResponseProtocol: ...


class RequestsExceptionsProtocol(Protocol):
    Timeout: type[Exception]
    RequestException: type[Exception]
    HTTPError: type[Exception]


class _RequestsModuleProtocol(Protocol):
    def Session(self, *args: Any, **kwargs: Any) -> SessionProtocol: ...

    exceptions: RequestsExceptionsProtocol
    Response: type[ResponseProtocol]


requests_module: _RequestsModuleProtocol | None
Response: type[ResponseProtocol]
requests_exceptions: RequestsExceptionsProtocol


if typing.TYPE_CHECKING:  # pragma: no cover - typing time placeholders
    import requests as _requests_mod  # type: ignore[import-untyped]  # noqa: F401
    from requests import exceptions as _RequestsExceptions  # noqa: F401
    from requests import Response as _RequestsResponse  # noqa: F401


def _initialize_requests() -> tuple[
    _RequestsModuleProtocol | None,
    type[ResponseProtocol],
    RequestsExceptionsProtocol,
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
            RequestsExceptionsProtocol, _FallbackRequestsExceptions()
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
            cast(type[ResponseProtocol], _FallbackResponse),
            fallback_exceptions,
        )

    _typed_requests = cast(_RequestsModuleProtocol, _requests_module)
    response_type = cast(type[ResponseProtocol], _requests_module.Response)
    exceptions = cast(RequestsExceptionsProtocol, _requests_module.exceptions)
    return _typed_requests, response_type, exceptions


requests_module, Response, requests_exceptions = _initialize_requests()


def create_session(*args: Any, **kwargs: Any) -> SessionProtocol:
    """Create a ``requests.Session`` if available."""

    if requests_module is None:
        raise ImportError("requests is required unless a session is provided")
    return requests_module.Session(*args, **kwargs)


__all__ = [
    "Response",
    "ResponseProtocol",
    "SessionProtocol",
    "RequestsExceptionsProtocol",
    "create_session",
    "requests_exceptions",
]
