"""State helpers for parallel runner execution."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any, cast, TYPE_CHECKING
from uuid import uuid4

from .config import ProviderConfig
from .datasets import GoldenTask
from .metrics import BudgetSnapshot, EvalMetrics, now_ts, RunMetrics
from .providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig
    from .runner_execution import SingleRunResult

    _ResultSeq = Sequence[SingleRunResult | None]
else:
    _ResultSeq = Sequence[object | None]

_single_run_result_cls: type[Any] | None = None


def _get_single_run_result_cls() -> type[SingleRunResult]:
    global _single_run_result_cls
    if _single_run_result_cls is None:
        from .runner_execution import SingleRunResult as _SingleRunResult

        _single_run_result_cls = _SingleRunResult
    return _single_run_result_cls


@dataclass(frozen=True, slots=True)
class ProviderFailureSummary:
    index: int
    provider: str
    status: str
    failure_kind: str | None
    error_message: str | None
    backoff_next_provider: bool
    retries: int
    error_type: str | None


if TYPE_CHECKING:
    _BuildSummary = Callable[
        [int, ProviderConfig, SingleRunResult],
        ProviderFailureSummary,
    ]
else:
    _BuildSummary = Callable[[int, ProviderConfig, object], ProviderFailureSummary]


class ParallelAnyState:
    def __init__(self, cancel_event: Event) -> None:
        self._cancel_event = cancel_event
        self._failure_lock = Lock()
        self._winner_lock = Lock()
        self._failure_indices: set[int] = set()
        self._failure_summaries: list[ProviderFailureSummary] = []
        self._winner_index: int | None = None
        self._caught_error: Exception | None = None

    def should_cancel(self) -> bool:
        return self._cancel_event.is_set()

    def register_failure(self, index: int, summary: ProviderFailureSummary) -> None:
        with self._failure_lock:
            self._failure_indices.add(index)
            self._failure_summaries.append(summary)

    def register_success(self, index: int) -> bool:
        with self._winner_lock:
            if self._winner_index is None:
                self._winner_index = index
                self._cancel_event.set()
                return False
            return self._winner_index != index

    def record_caught_error(self, exc: Exception) -> None:
        self._caught_error = exc

    def finalize(
        self,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        results: _ResultSeq,
        build_summary: _BuildSummary,
        error_factory: Callable[[str], Exception],
    ) -> None:
        success_found = any(
            result is not None and getattr(result.metrics, "status", None) == "ok"
            for result in results
        )
        if success_found:
            return
        for index, result in enumerate(results):
            if result is None or index in self._failure_indices:
                continue
            provider_config, _ = providers[index]
            summary = build_summary(index, provider_config, cast("SingleRunResult", result))
            self._failure_indices.add(index)
            self._failure_summaries.append(summary)
        error = error_factory("parallel-any failed")
        error_any = cast(Any, error)
        error_any.failures = self._failure_summaries
        error_any.batch = [
            (index, cast("SingleRunResult", result))
            for index, result in enumerate(results)
            if result is not None
        ]
        if self._caught_error is not None:
            raise error from self._caught_error
        raise error


def build_cancelled_result(
    provider_config: ProviderConfig,
    task: GoldenTask,
    attempt_index: int,
    config: RunnerConfig,
    cancel_message: str,
) -> SingleRunResult:
    metrics = RunMetrics(
        ts=now_ts(),
        run_id=f"run_{task.task_id}_{attempt_index}_{uuid4().hex}",
        provider=provider_config.provider,
        model=provider_config.model,
        mode=config.mode,
        prompt_id=task.task_id,
        prompt_name=task.name,
        seed=provider_config.seed,
        temperature=provider_config.temperature,
        top_p=provider_config.top_p,
        max_tokens=provider_config.max_tokens,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        cost_usd=0.0,
        status="skip",
        failure_kind="cancelled",
        error_message=cancel_message,
        output_text=None,
        output_hash=None,
        eval=EvalMetrics(),
        budget=BudgetSnapshot(0.0, False),
        ci_meta={},
    )
    single_run_result_cls = _get_single_run_result_cls()
    return single_run_result_cls(
        metrics=metrics,
        raw_output="",
        stop_reason="cancelled",
    )


__all__ = [
    "ProviderFailureSummary",
    "ParallelAnyState",
    "build_cancelled_result",
]
