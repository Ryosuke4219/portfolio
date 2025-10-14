from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError
from typing import Any

import pytest
from llm_adapter.provider_spi import ProviderRequest
from llm_adapter.runner_sync_invocation import (
    CancelledResultsBuilder,
    ParallelResultLogger,
    ProviderInvocationResult,
)

from .conftest import RecorderLogger, StubProvider


@pytest.fixture
def cancelled_builder() -> CancelledResultsBuilder:
    return CancelledResultsBuilder(run_started=1.0, elapsed_ms=lambda start: 99)


@pytest.fixture
def parallel_logger() -> ParallelResultLogger:
    return ParallelResultLogger(
        log_provider_call=lambda *a, **k: None,
        log_run_metric=lambda *a, **k: None,
        estimate_cost=lambda provider, tokens_in, tokens_out: 0.0,
        elapsed_ms=lambda start: 13,
    )


def test_cancelled_results_skip_metrics(
    stub_provider_factory: Callable[[str], StubProvider],
    cancelled_builder: CancelledResultsBuilder,
    parallel_logger: ParallelResultLogger,
    provider_request: ProviderRequest,
    recorder_logger: RecorderLogger,
) -> None:
    providers = [stub_provider_factory("primary"), stub_provider_factory("secondary")]
    results: list[ProviderInvocationResult | None] = [None, None]

    cancelled_builder.apply(results, providers=providers, cancelled_indices=[0, 1], total_providers=2)

    assert all(isinstance(entry, ProviderInvocationResult) for entry in results)
    assert all(isinstance(entry.error, CancelledError) for entry in results if entry is not None)

    log_run_metric_calls: list[dict[str, Any]] = []

    def fake_log_run_metric(*_: Any, **kwargs: Any) -> None:
        log_run_metric_calls.append(dict(kwargs))

    logger = ParallelResultLogger(
        log_provider_call=lambda *a, **k: None,
        log_run_metric=fake_log_run_metric,
        estimate_cost=lambda provider, tokens_in, tokens_out: 0.0,
        elapsed_ms=lambda start: 13,
    )

    logger.log_results(
        results,
        event_logger=recorder_logger,
        request=provider_request,
        request_fingerprint="fp",
        metadata={},
        run_started=0.0,
        shadow_used=False,
        skip=tuple(result for result in results if result is not None),
    )

    assert log_run_metric_calls == []
    assert all(isinstance(entry.error, CancelledError) for entry in results if entry is not None)
