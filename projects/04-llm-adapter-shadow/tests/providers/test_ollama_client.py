"""Thin HTTP client for the Ollama local API with auto model management."""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Any, Protocol, cast

from ..errors import AuthError, RateLimitError, RetriableError, TimeoutError
# 既存の互換層に揃える（tests で requests_exceptions を参照しているため）
from ._requests_compat import (
    requests,
    requests_exceptions,
)  # requests が無い環境では None の可能性あり


DEFAULT_HOST = "http://127.0.0.1:11434"

__all__ = ["OllamaClient", "DEFAULT_HOST"]


# ------------------------------------------------------------------------------
# HTTP プロトコル（最小限）
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


# ------------------------------------------------------------------------------
# クライアント本体
# ------------------------------------------------------------------------------

class OllamaClient:
    """HTTP facade for Ollama API. Public methods return a Response-like object.
    tests/helpers/fakes.FakeSession / FakeResponse と親和性を持たせる。
    """

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
            if requests is None:
                raise ImportError("requests is required unless a session is provided")
            session = requests.Session()
        self._session = session
        self._timeout = float(timeout)
        self._pull_timeout = float(pull_timeout)
        self._auto_pull = bool(auto_pull)
        self._ready_models: set[str] = set()

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _url(base: str, path: str) -> str:
        return f"{base}{path if path.startswith('/') else '/'+path}"

    # 例外マッピング（HTTP ステータス）
    @staticmethod
    def _raise_for_status_with_mapping(response: _ResponseProtocol) -> None:
        try:
            response.raise_for_status()
        except requests_exceptions.HTTPError as exc:  # type: ignore[attr-defined]
            status = getattr(response, "status_code", None)
            try:
                response.close()
            finally:
                if status in {401, 403}:
                    raise AuthError(str(exc)) from exc
                if status == 429:
                    raise RateLimitError(str(exc)) from exc
                if status in {408, 504}:
                    raise TimeoutError(str(exc)) from exc
                if isinstance(status, int) and status >= 500:
                    raise RetriableError(str(exc)) from exc
                raise RetriableError(str(exc)) from exc

    # 例外マッピング（接続例外）
    @staticmethod
    def _map_session_exception(exc: BaseException) -> BaseException:
        if isinstance(exc, requests_exceptions.Timeout):  # type: ignore[attr-defined]
            return TimeoutError(str(exc))
        # ConnectionError は Requ
