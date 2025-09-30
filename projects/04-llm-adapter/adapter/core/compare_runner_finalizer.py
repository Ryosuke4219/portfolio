"""タスク完了処理ヘルパー。"""
from __future__ import annotations

from collections.abc import Sequence
import json
import logging
from pathlib import Path
from statistics import median, pstdev
from typing import TYPE_CHECKING

from .config import ProviderConfig
from .datasets import GoldenTask
from .metrics import compute_diff_rate, RunMetrics
from .providers import BaseProvider

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_execution import SingleRunResult

LOGGER = logging.getLogger(__name__)

__all__ = ["TaskFinalizer", "DeterminismGate"]


class DeterminismGate:
    """決定性ゲート判定を担当する。"""

    def apply(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        metrics_list: Sequence[RunMetrics],
        outputs: Sequence[str],
    ) -> None:
        gates = provider_config.quality_gates
        if gates.determinism_diff_rate_max <= 0 and gates.determinism_len_stdev_max <= 0:
            return
        comparable: list[tuple[RunMetrics, str]] = [
            (metrics, output)
            for metrics, output in zip(metrics_list, outputs, strict=False)
            if metrics.status == "ok" and output
        ]
        if len(comparable) < 2:
            return
        diff_rates: list[float] = []
        for idx, (_, output_a) in enumerate(comparable):
            for _, output_b in comparable[idx + 1 :]:
                diff_rates.append(compute_diff_rate(output_a, output_b))
        median_diff = median(diff_rates) if diff_rates else 0.0
        lengths: list[int] = [
            metrics.eval.len_tokens
            if metrics.eval.len_tokens is not None
            else metrics.output_tokens
            for metrics, _ in comparable
        ]
        len_stdev = pstdev(lengths) if len(lengths) > 1 else 0.0
        diff_threshold_exceeded = (
            gates.determinism_diff_rate_max > 0
            and median_diff > gates.determinism_diff_rate_max
        )
        len_threshold_exceeded = (
            gates.determinism_len_stdev_max > 0
            and len_stdev > gates.determinism_len_stdev_max
        )
        if not (diff_threshold_exceeded or len_threshold_exceeded):
            return
        LOGGER.warning(
            "決定性ゲート失敗: provider=%s model=%s prompt=%s median_diff=%.4f len_stdev=%.4f",
            provider_config.provider,
            provider_config.model,
            task.task_id,
            median_diff,
            len_stdev,
        )
        for metrics, _ in comparable:
            metrics.status = "error"
            metrics.failure_kind = "non_deterministic"


class TaskFinalizer:
    """タスクの後処理を担当する。"""

    def __init__(self, metrics_path: Path, determinism_gate: DeterminismGate | None = None) -> None:
        self._metrics_path = metrics_path
        self._determinism_gate = determinism_gate or DeterminismGate()

    @property
    def metrics_path(self) -> Path:
        return self._metrics_path

    def update_metrics_path(self, metrics_path: Path) -> None:
        self._metrics_path = metrics_path

    def finalize_task(
        self,
        task: GoldenTask,
        providers: Sequence[tuple[ProviderConfig, BaseProvider]],
        histories: Sequence[Sequence[SingleRunResult]],
        results: list[RunMetrics],
    ) -> None:
        for index, (provider_config, _) in enumerate(providers):
            attempts = list(histories[index])
            if not attempts:
                continue
            metrics_list = [attempt.metrics for attempt in attempts]
            outputs = [attempt.raw_output for attempt in attempts]
            self._apply_determinism_gate(provider_config, task, metrics_list, outputs)
            for attempt in attempts:
                results.append(attempt.metrics)
                self._append_metric(attempt.metrics)

    def _apply_determinism_gate(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        metrics_list: Sequence[RunMetrics],
        outputs: Sequence[str],
    ) -> None:
        self._determinism_gate.apply(provider_config, task, metrics_list, outputs)

    def _append_metric(self, metrics: RunMetrics) -> None:
        with self._metrics_path.open("a", encoding="utf-8") as fp:
            json.dump(metrics.to_json_dict(), fp, ensure_ascii=False)
            fp.write("\n")
