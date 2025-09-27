"""HTTP helpers and fallbacks for the Ollama provider."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol

from ...errors import RetriableError, TimeoutError

__all__ = [
    "ResponseProtocol",
    "SessionProtocol",
    "create_default_session",
    "requests_exceptions",
    "send_request",
    "combine_host",
]


class ResponseProtocol(Protocol):
    """Subset of the :mod:`requests` response interface used by the provider."""

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
    """Minimal session interface required for issuing HTTP requests."""

    def post(self, url: str, *args: Any, **kwargs: Any) -> ResponseProtocol: ...


if TYPE_CHECKING:  # pragma: no cover - typing time placeholders
    requests: Any
    Response = ResponseProtocol
    requests_exceptions: Any
else:  # pragma: no cover - allow running without the optional dependency
    try:
        _requests_module = importlib.import_module("requests")
    except ModuleNotFoundError:
        requests = None

        class _FallbackRequestsExceptions:  # pragma: no cover - trivial container
            class RequestException(Exception): ...

            class Timeout(RequestException): ...

            class HTTPError(RequestException):
                def __init__(self, message: str | None = None, response: Any | None = None):
                    super().__init__(message or "HTTP error")
                    self.response = response

        requests_exceptions = _FallbackRequestsExceptions()

        class Response:  # pragma: no cover - stub
            """Very small stub mimicking the subset of Response we rely on."""

            status_code: int

            def __init__(self, status_code: int = 200) -> None:
                self.status_code = status_code

            def close(self) -> None:
                return None

            def __enter__(self) -> Response:
                return self

            def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
            ) -> bool | None:
                return None

            def json(self) -> Any:
                return {}

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    raise requests_exceptions.HTTPError(response=self)

            def iter_lines(self) -> Iterable[bytes]:
                return []

    else:
        requests = _requests_module
        Response = _requests_module.Response
        requests_exceptions = _requests_module.exceptions


def create_default_session() -> SessionProtocol:
    """Create a default :mod:`requests` session, raising if unavailable."""

    if requests is None:  # pragma: no cover - defensive branch
        raise ImportError("requests is required unless a session is provided")
    return requests.Session()


def combine_host(base: str, path: str) -> str:
    """Combine the API host and relative path."""

    if base.endswith("/"):
        base = base[:-1]
    return f"{base}{path}"


def send_request(
    session: SessionProtocol,
    host: str,
    default_timeout: float,
    path: str,
    payload: Mapping[str, Any],
    *,
    stream: bool = False,
    timeout: float | None = None,
) -> ResponseProtocol:
    """Issue a POST request against the Ollama API."""

    url = combine_host(host, path)
    try:
        response = session.post(
            url,
            json=payload,
            stream=stream,
            timeout=timeout or default_timeout,
        )
    except requests_exceptions.Timeout as exc:  # pragma: no cover - error handling
        raise TimeoutError(f"Ollama request timed out: {url}") from exc
    except requests_exceptions.RequestException as exc:  # pragma: no cover
        raise RetriableError(f"Ollama request failed: {url}") from exc
    return response
