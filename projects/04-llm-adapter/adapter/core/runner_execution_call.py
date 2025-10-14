"""Helper utilities for provider call attempts in :mod:`runner_execution`."""

from __future__ import annotations

from time import sleep
from types import MethodType
from typing import TYPE_CHECKING

from ._provider_execution import _ProviderCallResult, ProviderCallExecutor
from .config import ProviderConfig
from .errors import RateLimitError, RetryableError
from .providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .execution.guards import _TokenBucket


def execute_provider_with_retries(
    executor: ProviderCallExecutor,
    provider_config: ProviderConfig,
    provider: BaseProvider,
    prompt: str,
    *,
    token_bucket: _TokenBucket | None,
) -> _ProviderCallResult:
    """Call a provider until a successful result or retry budget is exhausted."""

    ensure_invoke_compat(provider)

    retries_config = provider_config.retries
    max_attempts = max(0, retries_config.max) + 1
    attempt = 0
    provider_result: _ProviderCallResult | None = None

    while attempt < max_attempts:
        if token_bucket is not None:
            token_bucket.acquire()
        attempt += 1
        provider_result = executor.execute(provider_config, provider, prompt)
        provider_result.retries = attempt
        if provider_result.status == "ok":
            break

        error = provider_result.error
        if provider_result.backoff_next_provider:
            if isinstance(error, RateLimitError) and attempt < max_attempts:
                pass
            else:
                break
        if attempt >= max_attempts:
            break
        if not isinstance(error, RetryableError):
            break
        backoff_delay = float(retries_config.backoff_s or 0.0)
        if backoff_delay > 0.0:
            sleep(backoff_delay)

    if provider_result is None:  # pragma: no cover - defensive
        raise RuntimeError("provider call did not yield a result")
    return provider_result


def ensure_invoke_compat(provider: BaseProvider) -> None:
    """Provide a generate()-based fallback for legacy providers."""

    generate = getattr(provider, "generate", None)
    if generate is None:
        return
    invoke_attr = getattr(type(provider), "invoke", None)
    if invoke_attr is not None and invoke_attr is not BaseProvider.invoke:
        return
    bound_generate = generate

    def _invoke(self: BaseProvider, request: object) -> object:
        prompt = getattr(request, "prompt", request)
        return bound_generate(prompt)

    setattr(provider, "invoke", MethodType(_invoke, provider))


__all__ = ["execute_provider_with_retries", "ensure_invoke_compat"]
