from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import time
from typing import Any, NamedTuple, cast

from src.llm_adapter.observability import CompositeLogger, EventLogger, JsonlLogger
from src.llm_adapter.parallel_exec import (
    ParallelAllResult,
    run_parallel_all_sync,
    run_parallel_any_sync,
)
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerConfig, RunnerMode
from src.llm_adapter.runner_shared import MetricsPath
from src.llm_adapter.runner_sync import Runner
from src.llm_adapter.runner_sync_invocation import ProviderInvocationResult
from src.llm_adapter.runner_sync_modes import SyncRunContext, get_sync_strategy
from src.llm_adapter.utils import content_hash

from ..parallel_helpers import RecordingLogger, _read_metrics


class ExecutionResult(NamedTuple):
    logger: RecordingLogger
    metrics: list[dict[str, Any]]
    result: (
        ProviderResponse
        | ProviderInvocationResult
        | ParallelAllResult[ProviderInvocationResult, ProviderResponse]
        | None
    )
    error: Exception | None


def build_context(
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


def execute_strategy(
    mode: RunnerMode,
    providers: Sequence[ProviderSPI],
    *,
    tmp_path: Path,
    request: ProviderRequest,
) -> ExecutionResult:
    metrics_path = tmp_path / f"{mode.value}-metrics.jsonl"
    config = RunnerConfig(mode=mode, metrics_path=metrics_path)
    recording_logger = RecordingLogger()
    json_logger = JsonlLogger(metrics_path)
    composite_logger = CompositeLogger((recording_logger, json_logger))
    runner = Runner(providers, logger=composite_logger, config=config)
    context = build_context(
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
    return ExecutionResult(
        logger=recording_logger,
        metrics=metrics,
        result=result,
        error=error,
    )


def run_metric_records_from_logger(logger: RecordingLogger) -> list[dict[str, Any]]:
    return [
        {
            "provider": record.get("provider"),
            "status": record.get("status"),
            "attempts": record.get("attempts"),
            "error_type": record.get("error_type"),
        }
        for record in logger.of_type("run_metric")
    ]


def run_metric_records_from_metrics(
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


def sorted_records(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda item: (
            "" if item["provider"] is None else str(item["provider"]),
            item["attempts"],
            item["status"],
            item["error_type"] or "",
        ),
    )


__all__ = [
    "ExecutionResult",
    "build_context",
    "execute_strategy",
    "run_metric_records_from_logger",
    "run_metric_records_from_metrics",
    "sorted_records",
]
