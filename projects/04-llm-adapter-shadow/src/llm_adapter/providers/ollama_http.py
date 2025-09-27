"""HTTP helpers for the Ollama provider."""

from __future__ import annotations

import importlib
import time
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, cast

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError


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


if TYPE_CHECKING:  # pragma: no cover - typing placeholders
    import requests as _requests_type  # type: ignore[import-not-found]

    requests = cast(Any, _requests_type)
    Response = cast(type[ResponseProtocol], _requests_type.Response)
    requests_exceptions = cast(Any, _requests_type.exceptions)
else:  # pragma: no cover - allow running without the optional dependency
    try:
        _requests_module = importlib.import_module("requests")
    except ModuleNotFoundError:
        requests = None

        class _FallbackRequestsExceptions:  # pragma: no cover - simple container
            class RequestException(Exception): ...

            class Timeout(RequestException): ...

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
        Response = cast(type[ResponseProtocol], _requests_module.Response)
        requests_exceptions = cast(Any, _requests_module.exceptions)


def _combine_host(base: str, path: str) -> str:
    if base.endswith("/"):
        base = base[:-1]
    return f"{base}{path}"


class OllamaHTTPClient:
    """Encapsulates HTTP operations for the Ollama provider."""

    def __init__(
        self,
        *,
        host: str,
        session: SessionProtocol | None,
        timeout: float,
        pull_timeout: float,
        auto_pull: bool,
    ) -> None:
        if session is None:
            if requests is None:  # pragma: no cover - defensive branch
                raise ImportError("requests is required unless a session is provided")
            session = requests.Session()
        self._host = host
        self._session = session
        self._timeout = timeout
        self._pull_timeout = pull_timeout
        self._auto_pull = auto_pull
        self._ready_models: set[str] = set()

    @property
    def host(self) -> str:
        return self._host

    @property
    def session(self) -> SessionProtocol:
        return self._session

    @property
    def ready_models(self) -> set[str]:
        return self._ready_models

    def request(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        stream: bool = False,
        timeout: float | None = None,
    ) -> ResponseProtocol:
        url = _combine_host(self._host, path)
        try:
            response = self._session.post(
                url,
                json=payload,
                stream=stream,
                timeout=timeout or self._timeout,
            )
        except requests_exceptions.Timeout as exc:  # pragma: no cover - error mapping
            raise TimeoutError(f"Ollama request timed out: {url}") from exc
        except requests_exceptions.RequestException as exc:  # pragma: no cover
            raise RetriableError(f"Ollama request failed: {url}") from exc
        return response

    def ensure_model(self, model_name: str) -> None:
        if model_name in self._ready_models:
            return

        show_response = self.request("/api/show", {"model": model_name})
        if show_response.status_code == 200:
            self._ready_models.add(model_name)
            show_response.close()
            return
        show_response.close()

        if not self._auto_pull:
            raise RetriableError(f"ollama model not available: {model_name}")

        with self.request(
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
            show_after = self.request("/api/show", {"model": model_name})
            if show_after.status_code == 200:
                self._ready_models.add(model_name)
                show_after.close()
                return
            show_after.close()
            time.sleep(1)

        raise RetriableError(f"failed to pull ollama model: {model_name}")

    def chat(self, payload: Mapping[str, Any], *, timeout: float | None) -> Mapping[str, Any]:
        response = self.request("/api/chat", payload, timeout=timeout)
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

            return response.json()
        except ValueError as exc:
            raise RetriableError("invalid JSON from Ollama") from exc
        finally:
            response.close()


__all__ = [
    "OllamaHTTPClient",
    "Response",
    "ResponseProtocol",
    "SessionProtocol",
    "requests",
    "requests_exceptions",
]

