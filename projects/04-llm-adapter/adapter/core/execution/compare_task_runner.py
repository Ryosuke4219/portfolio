from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
from enum import Enum
from typing import Any, TYPE_CHECKING

from ..config import ProviderConfig
from ..datasets import GoldenTask
from ..errors import AllFailedError
from ..metrics import RunMetrics
from ..providers import BaseProvider, ProviderFactory
from ..runner_execution import RunnerExecution, SingleRunResult

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from ..runner_api import RunnerConfig


LOGGER = logging.getLogger(__name__)


def run_tasks(
    *,
    provider_configs: Sequence[ProviderConfig],
    tasks: Sequence[GoldenTask],
    repeat: int,
    config: RunnerConfig,
    execution: RunnerExecution,
    aggregation_apply: Callable[..., None],
    finalize_task: Callable[..., None],
    judge_provider_config: ProviderConfig | None,
    record_failed_batch: Callable[..., None],
    log_attempt_failures: Callable[[str, Sequence[object]], None],
    parallel_execution_error: type[Exception],
) -> list[RunMetrics]:
    providers: list[tuple[ProviderConfig, BaseProvider]] = [
        (provider_config, ProviderFactory.create(provider_config))
        for provider_config in provider_configs
    ]
    for provider_config, _ in providers:
        LOGGER.info(
            "provider=%s model=%s を実行",
            provider_config.provider,
            provider_config.model,
        )
    results: list[RunMetrics] = []
    if not providers:
        return results

    mode_value = _mode_value(config.mode)

    stop_reason: str | None = None
    for task in tasks:
        histories: list[list[SingleRunResult]] = [[] for _ in providers]
        for attempt in range(repeat):
            try:
                if _mode_equals(config.mode, "sequential"):
                    batch, stop_reason = execution.run_sequential_attempt(
                        providers, task, attempt, mode_value
                    )
                else:
                    batch, stop_reason = execution.run_parallel_attempt(
                        providers, task, attempt, config
                    )
            except AllFailedError as exc:
                _handle_failure(
                    config,
                    histories,
                    exc,
                    record_failed_batch,
                    log_attempt_failures,
                    f"タスク{task.task_id}の試行{attempt}で全プロバイダ失敗",
                )
                raise
            except Exception as exc:
                if isinstance(exc, parallel_execution_error):
                    _handle_failure(
                        config,
                        histories,
                        exc,
                        record_failed_batch,
                        log_attempt_failures,
                        f"タスク{task.task_id}の並列実行に失敗",
                    )
                raise
            aggregation_apply(
                mode=mode_value,
                config=config,
                batch=batch,
                default_judge_config=judge_provider_config,
            )
            for index, result in batch:
                histories[index].append(result)
            if stop_reason:
                break
        finalize_task(task, providers, histories, results)
        if stop_reason:
            LOGGER.warning("予算制約により実行を停止します: %s", stop_reason)
            break
    return results


def _handle_failure(
    config: RunnerConfig,
    histories: list[list[SingleRunResult]],
    exc: BaseException,
    record_failed_batch: Callable[..., None],
    log_attempt_failures: Callable[[str, Sequence[object]], None],
    message: str,
) -> None:
    batch: Sequence[tuple[int, SingleRunResult]] | Any = getattr(exc, "batch", [])
    failures = getattr(exc, "failures", ())
    log_attempt_failures(_mode_value(config.mode), failures)
    if batch:
        record_failed_batch(batch, config, histories)
    LOGGER.error(message, exc_info=exc)


def _mode_equals(mode: object, expected: str) -> bool:
    if isinstance(mode, Enum):
        return mode.value == expected
    return mode == expected


def _mode_value(mode: object) -> str:
    if isinstance(mode, Enum):
        value = mode.value
        if isinstance(value, str):
            return value
        return str(value)
    if isinstance(mode, str):
        return mode
    return str(mode)
