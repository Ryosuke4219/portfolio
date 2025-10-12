from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import time

import pytest
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerMode

from ..parallel_helpers import _StaticProvider
from .helpers import (
    execute_strategy,
    run_metric_records_from_logger,
    run_metric_records_from_metrics,
    sorted_records,
)


class _DelayedProvider(_StaticProvider):
    def __init__(self, name: str, text: str, latency_ms: int, delay: float) -> None:
        super().__init__(name, text, latency_ms)
        self._delay = delay

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        time.sleep(self._delay)
        return super().invoke(request)


@pytest.mark.parametrize(
    ("mode", "providers_factory", "expected_statuses"),
    [
        (
            RunnerMode.SEQUENTIAL,
            lambda: [_StaticProvider("seq", "sequential-ok", latency_ms=3)],
            [("seq", "ok", 1, None)],
        ),
        (
            RunnerMode.PARALLEL_ANY,
            lambda: [
                _StaticProvider("fast", "fast-ok", latency_ms=2),
                _DelayedProvider("slow", "slow-ok", latency_ms=10, delay=0.05),
            ],
            [
                ("fast", "ok", 2, None),
                ("slow", "ok", 2, None),
            ],
        ),
        (
            RunnerMode.PARALLEL_ALL,
            lambda: [
                _StaticProvider("all-a", "A", latency_ms=3),
                _StaticProvider("all-b", "B", latency_ms=4),
            ],
            [
                ("all-a", "ok", 1, None),
                ("all-b", "ok", 2, None),
            ],
        ),
    ],
)
def test_get_sync_strategy_happy_paths(
    mode: RunnerMode,
    providers_factory: Callable[[], Sequence[ProviderSPI]],
    expected_statuses: Sequence[tuple[str, str, int, str | None]],
    tmp_path: Path,
) -> None:
    request = ProviderRequest(prompt="hello", model="gpt-test")
    result = execute_strategy(
        mode, providers_factory(), tmp_path=tmp_path, request=request
    )

    assert result.error is None
    assert result.result is not None

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
