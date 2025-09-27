"""Model management helpers for the Ollama provider."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Protocol, Any

from ...errors import AuthError, RateLimitError, RetriableError, TimeoutError
from .http import ResponseProtocol, requests_exceptions

__all__ = ["RequestCallable", "ensure_model"]


class RequestCallable(Protocol):
    """Callable signature for issuing Ollama API requests."""

    def __call__(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        stream: bool = False,
        timeout: float | None = None,
    ) -> ResponseProtocol: ...


def ensure_model(
    model_name: str,
    *,
    ready_models: set[str],
    auto_pull: bool,
    pull_timeout: float,
    request: RequestCallable,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Ensure the requested model is available, pulling it if necessary."""

    if model_name in ready_models:
        return

    show_response = request("/api/show", {"model": model_name})
    if show_response.status_code == 200:
        ready_models.add(model_name)
        show_response.close()
        return
    show_response.close()

    if not auto_pull:
        raise RetriableError(f"ollama model not available: {model_name}")

    with request(
        "/api/pull",
        {"model": model_name},
        stream=True,
        timeout=pull_timeout,
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
        show_after = request("/api/show", {"model": model_name})
        if show_after.status_code == 200:
            ready_models.add(model_name)
            show_after.close()
            return
        show_after.close()
        sleep(1)

    raise RetriableError(f"failed to pull ollama model: {model_name}")
