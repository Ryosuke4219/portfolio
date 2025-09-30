"""Attempt executor helpers for :mod:`adapter.core.runner_execution`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from .config import ProviderConfig
from .datasets import GoldenTask
from .errors import AllFailedError
from .providers import BaseProvider
from .runner_execution_parallel import (
    ParallelAttemptExecutor,
    ProviderFailureSummary,
)

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_execution import SingleRunResult

_RunSingle = Callable[[ProviderConfig, BaseProvider, GoldenTask, int, str], "SingleRunResult"]


class SequentialAttemptExecutor:
    """Executor to handle sequential provider attempts."""

    def __init__(self, run_single: _RunSingle) -> None:
        self._run_single = run_single

    def run(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> tuple[list[tuple[int, "SingleRunResult"]], str | None]:
        batch: list[tuple[int, "SingleRunResult"]] = []
        stop_reason: str | None = None
        failures: list[ProviderFailureSummary] = []
        success_found = False
        for index, (provider_config, provider) in enumerate(providers):
            result = self._run_single(provider_config, provider, task, attempt_index, mode)
            batch.append((index, result))
            metrics = result.metrics
            if result.stop_reason and not stop_reason:
                stop_reason = result.stop_reason
            if metrics.status == "ok":
                success_found = True
                break
            failures.append(
                ProviderFailureSummary(
                    index=index,
                    provider=provider_config.provider,
                    status=metrics.status,
                    failure_kind=metrics.failure_kind,
                    error_message=metrics.error_message,
                    backoff_next_provider=result.backoff_next_provider,
                    retries=metrics.retries,
                    error_type=type(result.error).__name__ if result.error else None,
                )
            )
        if not success_found:
            error = AllFailedError("all providers failed")
            error.failures = failures  # type: ignore[attr-defined]
            error.batch = batch  # type: ignore[attr-defined]
            error.stop_reason = stop_reason  # type: ignore[attr-defined]
            raise error
        return batch, stop_reason


__all__ = [
    "SequentialAttemptExecutor",
    "ParallelAttemptExecutor",
    "ProviderFailureSummary",
]

