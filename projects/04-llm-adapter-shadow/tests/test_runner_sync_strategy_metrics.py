from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import time
from typing import Any, cast, NamedTuple

import pytest

from src.llm_adapter.errors import AllFailedError, TimeoutError
from src.llm_adapter.observability import CompositeLogger, EventLogger, JsonlLogger
from src.llm_adapter.parallel_exec import (
    ParallelAllResult,
    ParallelExecutionError,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode
from src.llm_adapter.runner_shared import MetricsPath
from src.llm_adapter.runner_sync import Runner
from src.llm_adapter.runner_sync_invocation import ProviderInvocationResult
from src.llm_adapter.runner_sync_modes import get_sync_strategy, SyncRunContext
from src.llm_adapter.utils import content_hash

from .parallel_helpers import RecordingLogger, _StaticProvider, _read_metrics


class _DelayedProvider(_StaticProvider):
    def __init__(self, name: str, text: str, latency_ms: int, delay: float) -> None:
        super().__init__(name, text, latency_ms)
        self._delay = delay

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        time.sleep(self._delay)
        return super().invoke(request)


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


class _ExecutionResult(NamedTuple):
    logger: RecordingLogger
    metrics: list[dict[str, Any]]
    result: (
        ProviderResponse
        | ProviderInvocationResult
        | ParallelAllResult[ProviderInvocationResult, ProviderResponse]
        | None
    )
    error: Exception | None


def _build_context(
    runner: Runner,
    request: ProviderRequest,
    *,
    event_logger: EventLogger | None,
    metrics_path: MetricsPath,
) -> SyncRunContext:
    request_fingerprint = content_hash(
        "runner",
        request.prompt_text,
        request.options,
        request.max_tokens,
    )
    mode_value = getattr(runner._config.mode, "value", str(runner._config.mode))
    metadata = {
        "run_id": request_fingerprint,
        "mode": mode_value,
        "providers": [provider.name() for provider in runner.providers],
        "shadow_used": False,
        "shadow_provider_id": None,
    }
    return SyncRunContext(
        runner=runner,
        request=request,
        event_logger=event_logger,
        metadata=metadata,
        run_started=time.time(),
        request_fingerprint=request_fingerprint,
        shadow=None,
        shadow_used=False,
        metrics_path=str(metrics_path),
        run_parallel_all=run_parallel_all_sync,
        run_parallel_any=run_parallel_any_sync,
    )


def _execute_strategy(
    mode: RunnerMode,
    providers: Sequence[ProviderSPI],
    *,
    tmp_path: Path,
    request: ProviderRequest,
) -> _ExecutionResult:
    metrics_path = tmp_path / f"{mode.value}-metrics.jsonl"
    config = RunnerConfig(mode=mode, metrics_path=metrics_path)
    recording_logger = RecordingLogger()
    json_logger = JsonlLogger(metrics_path)
    composite_logger = CompositeLogger((recording_logger, json_logger))
    runner = Runner(providers, logger=composite_logger, config=config)
    context = _build_context(
        runner,
        request,
        event_logger=composite_logger,
        metrics_path=metrics_path,
    )
    mode_enum = cast(RunnerMode, config.mode)
    strategy = get_sync_strategy(mode_enum)

    try:
        result = strategy.execute(context)
        error: Exception | None = None
    except Exception as exc:  # pragma: no cover - exercised by error cases
        result = None
        error = exc

    metrics = _read_metrics(metrics_path) if metrics_path.exists() else []
    return _ExecutionResult(
        logger=recording_logger, metrics=metrics, result=result, error=error
    )


def _run_metric_records_from_logger(logger: RecordingLogger) -> list[dict[str, Any]]:
    return [
        {
            "provider": record.get("provider"),
            "status": record.get("status"),
            "attempts": record.get("attempts"),
            "error_type": record.get("error_type"),
        }
        for record in logger.of_type("run_metric")
    ]


def _run_metric_records_from_metrics(
    metrics: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "provider": record.get("provider"),
            "status": record.get("status"),
            "attempts": record.get("attempts"),
            "error_type": record.get("error_type"),
        }
        for record in metrics
        if record.get("event") == "run_metric"
    ]


def _sorted_records(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda item: (
            "" if item["provider"] is None else str(item["provider"]),
            item["attempts"],
            item["status"],
            item["error_type"] or "",
        ),
    )


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
    result = _execute_strategy(
        mode, providers_factory(), tmp_path=tmp_path, request=request
    )

    assert result.error is None
    assert result.result is not None

    logger_records = _sorted_records(_run_metric_records_from_logger(result.logger))
    metrics_records = _sorted_records(_run_metric_records_from_metrics(result.metrics))
    assert logger_records == metrics_records
    expected_records = _sorted_records(
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
    result = _execute_strategy(
        mode, providers_factory(), tmp_path=tmp_path, request=request
    )

    assert result.error is not None
    assert isinstance(result.error, expected_error)
    assert result.result is None

    logger_records = _sorted_records(_run_metric_records_from_logger(result.logger))
    metrics_records = _sorted_records(_run_metric_records_from_metrics(result.metrics))
    assert logger_records == metrics_records
    expected_records = _sorted_records(
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
