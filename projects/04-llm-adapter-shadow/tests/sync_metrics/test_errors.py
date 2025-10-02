from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from src.llm_adapter.errors import AllFailedError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerMode

from ..parallel_helpers import _StaticProvider
from .helpers import (
    execute_strategy,
    run_metric_records_from_logger,
    run_metric_records_from_metrics,
    sorted_records,
)


class _FailingProvider:
    def __init__(self, name: str, error: Exception) -> None:
        self._name = name
        self._error = error

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        raise self._error


@pytest.mark.parametrize(
    ("mode", "providers_factory", "expected_error", "expected_statuses"),
    [
        (
            RunnerMode.SEQUENTIAL,
            lambda: [
                _FailingProvider("seq-fail-1", TimeoutError("slow")),
                _FailingProvider("seq-fail-2", TimeoutError("boom")),
            ],
            AllFailedError,
            [(None, "error", 2, "TimeoutError")],
        ),
        (
            RunnerMode.PARALLEL_ANY,
            lambda: [
                _FailingProvider("p-any-a", TimeoutError("slow")),
                _FailingProvider("p-any-b", TimeoutError("boom")),
            ],
            ParallelExecutionError,
            [
                ("p-any-a", "error", 1, "TimeoutError"),
                ("p-any-b", "error", 2, "TimeoutError"),
            ],
        ),
        (
            RunnerMode.PARALLEL_ALL,
            lambda: [
                _StaticProvider("all-ok", "ok", latency_ms=3),
                _FailingProvider("all-fail", TimeoutError("boom")),
            ],
            TimeoutError,
            [
                ("all-ok", "ok", 1, None),
                ("all-fail", "error", 2, "TimeoutError"),
            ],
        ),
    ],
)
def test_get_sync_strategy_error_paths(
    mode: RunnerMode,
    providers_factory: Callable[[], Sequence[ProviderSPI]],
    expected_error: type[Exception],
    expected_statuses: Sequence[tuple[str | None, str, int, str | None]],
    tmp_path: Path,
) -> None:
    request = ProviderRequest(prompt="[TIMEOUT] trigger", model="gpt-test")
    result = execute_strategy(
        mode, providers_factory(), tmp_path=tmp_path, request=request
    )

    assert result.error is not None
    assert isinstance(result.error, expected_error)
    assert result.result is None

    logger_records = sorted_records(
        run_metric_records_from_logger(result.logger)
    )
    metrics_records = sorted_records(
        run_metric_records_from_metrics(result.metrics)
    )
    assert logger_records == metrics_records
    expected_records = sorted_records(
        [
            {
                "provider": name,
                "status": status,
                "attempts": attempts,
                "error_type": error_type,
            }
            for name, status, attempts, error_type in expected_statuses
        ]
    )
    assert logger_records == expected_records
