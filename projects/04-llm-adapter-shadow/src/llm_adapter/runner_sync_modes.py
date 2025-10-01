"""Synchronous runner strategy implementations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from .observability import EventLogger
from .parallel_exec import ParallelAllResult, ParallelExecutionError
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .runner_config import RunnerMode
from .runner_shared import MetricsPath
from .runner_sync_parallel_any import (
    ParallelAnyCallable,
    ParallelAnyStrategy,
    _collect_parallel_failures,
    _limited_providers,
    _raise_no_attempts,
)
from .runner_sync_sequential import SequentialStrategy

if TYPE_CHECKING:
    from .runner_sync import ProviderInvocationResult, Runner


class ParallelAllCallable(Protocol):
    def __call__(
        self,
        workers: Sequence[Callable[[], ProviderInvocationResult]],
        *,
        max_concurrency: int | None = ...,
    ) -> Sequence[ProviderInvocationResult]: ...


@dataclass(slots=True)
class SyncRunContext:
    runner: Runner
    request: ProviderRequest
    event_logger: EventLogger | None
    metadata: dict[str, object]
    run_started: float
    request_fingerprint: str
    shadow: ProviderSPI | None
    shadow_used: bool
    metrics_path: MetricsPath
    run_parallel_all: ParallelAllCallable
    run_parallel_any: ParallelAnyCallable


class SyncRunStrategy(Protocol):
    def execute(
        self, context: SyncRunContext
    ) -> (
        ProviderResponse | ParallelAllResult[ProviderInvocationResult, ProviderResponse]
    ): ...




class ParallelAllStrategy:
    def execute(
        self, context: SyncRunContext
    ) -> (
        ProviderResponse | ParallelAllResult[ProviderInvocationResult, ProviderResponse]
    ):
        runner = context.runner
        total_providers = len(runner.providers)
        results: list[ProviderInvocationResult | None] = [None] * total_providers
        max_attempts = runner._config.max_attempts
        providers = _limited_providers(runner.providers, max_attempts)

        def make_worker(
            index: int, provider: ProviderSPI
        ) -> Callable[[], ProviderInvocationResult]:
            def worker() -> ProviderInvocationResult:
                result = runner._invoke_provider_sync(
                    provider,
                    context.request,
                    attempt=index,
                    total_providers=total_providers,
                    event_logger=context.event_logger,
                    request_fingerprint=context.request_fingerprint,
                    metadata=context.metadata,
                    shadow=context.shadow,
                    metrics_path=context.metrics_path,
                    capture_shadow_metrics=False,
                )
                results[index - 1] = result
                if result.response is None:
                    error = result.error
                    if error is not None:
                        raise error
                    error = ParallelExecutionError("provider returned no response")
                    result.error = error
                    raise error
                return result

            return worker

        workers = [
            make_worker(index, provider)
            for index, provider in enumerate(providers, start=1)
        ]
        if not workers:
            _raise_no_attempts(context)

        try:
            invocations = context.run_parallel_all(
                workers, max_concurrency=runner._config.max_concurrency
            )
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            for invocation in invocations:
                if invocation.response is None:
                    failures = _collect_parallel_failures(results)
                    raise ParallelExecutionError(
                        "all workers failed",
                        failures=failures or None,
                    )
            return ParallelAllResult(
                invocations,
                lambda invocation: cast(ProviderResponse, invocation.response),
            )
        except ParallelExecutionError as exc:
            fatal = runner._extract_fatal_error(results)
            if fatal is not None:
                raise fatal from None
            failures = _collect_parallel_failures(results)
            exc.failures = failures if failures else None
            raise exc
        finally:
            runner._log_parallel_results(
                results,
                event_logger=context.event_logger,
                request=context.request,
                request_fingerprint=context.request_fingerprint,
                metadata=context.metadata,
                run_started=context.run_started,
                shadow_used=context.shadow_used,
            )


# Imported at the end to avoid circular dependency with ConsensusStrategy helper imports.
from .runner_sync_consensus import ConsensusStrategy  # noqa: E402


def get_sync_strategy(mode: RunnerMode) -> SyncRunStrategy:
    if mode == RunnerMode.SEQUENTIAL:
        return SequentialStrategy()
    if mode == RunnerMode.PARALLEL_ANY:
        return ParallelAnyStrategy()
    if mode == RunnerMode.PARALLEL_ALL:
        return ParallelAllStrategy()
    if mode == RunnerMode.CONSENSUS:
        return ConsensusStrategy()
    raise RuntimeError(f"Unsupported runner mode: {mode}")


__all__ = [
    "SyncRunContext",
    "SyncRunStrategy",
    "_limited_providers",
    "_raise_no_attempts",
    "SequentialStrategy",
    "get_sync_strategy",
]
