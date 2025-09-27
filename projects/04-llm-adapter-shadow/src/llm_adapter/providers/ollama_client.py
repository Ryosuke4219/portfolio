from __future__ import annotations

from collections.abc import Mapping

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
from ._requests_compat import ResponseProtocol, SessionProtocol, requests_exceptions


def _combine_host(base: str, path: str) -> str:
    return f"{base[:-1] if base.endswith('/') else base}{path}"


class OllamaClient:
    __slots__ = ("_host", "_session", "_timeout", "_pull_timeout")

    def __init__(self, *, host: str, session: SessionProtocol, timeout: float, pull_timeout: float) -> None:
        self._host = host
        self._session = session
        self._timeout = timeout
        self._pull_timeout = pull_timeout

    def show(self, payload: Mapping[str, object]) -> ResponseProtocol:
        return self._post("/api/show", payload)

    def pull(self, payload: Mapping[str, object]) -> ResponseProtocol:
        return self._ensure_success(
            "/api/pull",
            self._post("/api/pull", payload, stream=True, timeout=self._pull_timeout),
        )

    def chat(self, payload: Mapping[str, object], *, timeout: float | None = None) -> ResponseProtocol:
        return self._ensure_success(
            "/api/chat",
            self._post("/api/chat", payload, timeout=timeout),
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
