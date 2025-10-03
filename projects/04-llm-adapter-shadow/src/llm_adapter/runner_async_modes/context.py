"""Shared context and result types for async runner strategies."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..observability import EventLogger
from ..parallel_exec import ParallelAllResult
from ..provider_spi import AsyncProviderSPI, ProviderRequest, ProviderResponse, ProviderSPI
from ..runner_config import RunnerConfig, RunnerMode
from ..shadow import ShadowMetrics

WorkerResult = tuple[
    int,
    ProviderSPI | AsyncProviderSPI,
    ProviderResponse | None,
    ShadowMetrics | None,
]
WorkerFactory = Callable[[], Awaitable[WorkerResult]]

InvokeProviderFn = Callable[
    [
        int,
        ProviderSPI | AsyncProviderSPI,
        AsyncProviderSPI,
        bool,
    ],
    Awaitable[tuple[ProviderResponse, ShadowMetrics | None]],
]


@dataclass
class AsyncRunContext:
    request: ProviderRequest
    providers: Sequence[tuple[ProviderSPI | AsyncProviderSPI, AsyncProviderSPI]]
    event_logger: EventLogger | None
    metadata: Mapping[str, Any]
    request_fingerprint: str
    run_started: float
    shadow: ProviderSPI | AsyncProviderSPI | None
    shadow_async: AsyncProviderSPI | None
    metrics_path: str | None
    config: RunnerConfig
    mode: RunnerMode
    invoke_provider: InvokeProviderFn
    sleep_fn: Callable[[float], Awaitable[None]]
    attempt_count: int = 0
    last_error: Exception | None = None
    results: list[WorkerResult] | None = None
    failure_records: list[dict[str, str] | None] = field(default_factory=list)
    attempted: list[bool] = field(default_factory=list)
    attempt_labels: list[int] = field(default_factory=list)
    pending_retry_events: dict[int, dict[str, Any]] = field(default_factory=dict)
    retry_attempts: int = 0

    def __post_init__(self) -> None:
        total = len(self.providers)
        if not self.failure_records:
            self.failure_records = [None] * total
        if not self.attempted:
            self.attempted = [False] * total
        if not self.attempt_labels:
            self.attempt_labels = [index for index in range(1, total + 1)]

    @property
    def total_providers(self) -> int:
        return len(self.providers)


@dataclass
class StrategyResult:
    value: ProviderResponse | ParallelAllResult[WorkerResult, ProviderResponse] | None
    attempt_count: int
    last_error: Exception | None
    results: list[WorkerResult] | None = None
    failure_details: list[dict[str, str]] | None = None


class AsyncRunStrategy(Protocol):
    async def run(self, context: AsyncRunContext) -> StrategyResult:  # pragma: no cover - protocol
        ...


def collect_failure_details(context: AsyncRunContext) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for index, was_attempted in enumerate(context.attempted):
        if not was_attempted:
            continue
        record = context.failure_records[index]
        if record is not None:
            details.append(dict(record))
            continue
        provider, _ = context.providers[index]
        details.append(
            {
                "provider": provider.name(),
                "attempt": str(context.attempt_labels[index]),
                "summary": "unknown error",
            }
        )
    return details
