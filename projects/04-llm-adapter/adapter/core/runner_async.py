"""最小限の非同期ランナー実装。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from .errors import (
    AllFailedError,
    ParallelExecutionError,
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config_builder import BackoffPolicy, RunnerConfig, RunnerMode

MetricsPath = Any


def _ensure_config(config: RunnerConfig | None) -> RunnerConfig:
    if config is not None:
        return config
    return RunnerConfig(mode=RunnerMode.SEQUENTIAL, backoff=BackoffPolicy())


def _error_family(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    if isinstance(exc, RateLimitError):
        return "rate_limit"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, RetriableError):
        return "retryable"
    return "fatal"


class AsyncRunner:
    """ProviderSPI を ``asyncio`` から扱うための薄いブリッジ。"""

    def __init__(
        self,
        providers: Sequence[ProviderSPI],
        *,
        logger: Any | None = None,
        config: RunnerConfig | None = None,
    ) -> None:
        if not providers:
            raise ValueError("AsyncRunner requires at least one provider")
        self._providers = list(providers)
        self._logger = logger
        self._config = _ensure_config(config)

    async def run_async(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | None = None,
        shadow_metrics_path: MetricsPath | None = None,
    ) -> ProviderResponse:
        del shadow, shadow_metrics_path
        errors: list[tuple[ProviderSPI, BaseException]] = []
        mode = RunnerMode(self._config.mode)
        for provider in self._providers:
            try:
                response = await asyncio.to_thread(provider.invoke, request)
            except Exception as exc:  # noqa: BLE001 - 上位で分類
                self._emit_provider_call(provider, "error", exc)
                errors.append((provider, exc))
                await self._apply_backoff(exc)
                continue
            self._emit_provider_call(provider, "ok", None)
            if mode is RunnerMode.CONSENSUS:
                return response
            return response
        if mode is RunnerMode.CONSENSUS and errors:
            last_provider, last_error = errors[-1]
            self._emit_chain_failed(len(errors), last_provider, last_error)
            raise ParallelExecutionError(
                "consensus run failed", failures=[err for _, err in errors]
            ) from last_error
        last_provider: ProviderSPI | None = None
        last_error: BaseException | None = None
        if errors:
            last_provider, last_error = errors[-1]
            self._emit_chain_failed(len(errors), last_provider, last_error)
            if last_error is not None:
                raise last_error
        raise AllFailedError("All providers failed to produce a result")

    async def _apply_backoff(self, error: BaseException) -> None:
        backoff = self._config.backoff
        delay = float(backoff.rate_limit_sleep_s or 0.0)
        if delay > 0.0 and isinstance(error, RateLimitError):
            await asyncio.sleep(delay)

    def _emit_provider_call(
        self, provider: ProviderSPI, status: str, error: BaseException | None
    ) -> None:
        if self._logger is None:
            return
        record = {
            "provider": provider.name(),
            "status": status,
            "error_type": type(error).__name__ if error else None,
            "error_family": _error_family(error),
        }
        self._logger.emit("provider_call", record)

    def _emit_chain_failed(
        self,
        attempts: int,
        provider: ProviderSPI | None,
        error: BaseException | None,
    ) -> None:
        if self._logger is None:
            return
        record = {
            "provider_attempts": attempts,
            "last_error_type": type(error).__name__ if error else None,
            "last_error_family": _error_family(error),
            "providers": [p.name() for p in self._providers],
            "last_provider": provider.name() if provider else None,
        }
        self._logger.emit("provider_chain_failed", record)


__all__ = ["AsyncRunner"]

