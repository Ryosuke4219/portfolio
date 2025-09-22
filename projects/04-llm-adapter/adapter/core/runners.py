"""比較ランナーの実装。"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from time import perf_counter
from statistics import median, pstdev
from typing import List, Mapping, Optional, Sequence, Tuple

from .budgets import BudgetManager
from .config import ProviderConfig
from .datasets import GoldenTask
from .metrics import (
    BudgetSnapshot,
    EvalMetrics,
    RunMetrics,
    compute_cost_usd,
    compute_diff_rate,
    hash_text,
    now_ts,
)
from .providers import BaseProvider, ProviderFactory, ProviderResponse

LOGGER = logging.getLogger(__name__)


class CompareRunner:
    """プロバイダ横断でゴールデンタスクを評価する。"""

    def __init__(
        self,
        provider_configs: Sequence[ProviderConfig],
        tasks: Sequence[GoldenTask],
        budget_manager: BudgetManager,
        metrics_path: Path,
        allow_overrun: bool = False,
    ) -> None:
        self.provider_configs = list(provider_configs)
        self.tasks = list(tasks)
        self.budget_manager = budget_manager
        self.metrics_path = metrics_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.allow_overrun = allow_overrun

    def run(self, repeat: int, mode: str) -> List[RunMetrics]:
        results: List[RunMetrics] = []
        for provider_config in self.provider_configs:
            provider = ProviderFactory.create(provider_config)
            LOGGER.info("provider=%s model=%s を実行", provider_config.provider, provider_config.model)
            for task in self.tasks:
                attempt_metrics: List[RunMetrics] = []
                attempt_outputs: List[str] = []
                stop_reason: Optional[str] = None
                for attempt in range(repeat):
                    metrics, raw_output, budget_reason = self._run_single(
                        provider_config, provider, task, attempt, mode
                    )
                    attempt_metrics.append(metrics)
                    attempt_outputs.append(raw_output)
                    if budget_reason:
                        stop_reason = budget_reason
                        break
                self._apply_determinism_gate(
                    provider_config, task, attempt_metrics, attempt_outputs
                )
                for metrics in attempt_metrics:
                    results.append(metrics)
                    self._append_metric(metrics)
                if stop_reason:
                    LOGGER.warning("予算制約により実行を停止します: %s", stop_reason)
                    return results
        return results

    def _run_single(
        self,
        provider_config: ProviderConfig,
        provider: BaseProvider,
        task: GoldenTask,
        attempt_index: int,
        mode: str,
    ) -> Tuple[RunMetrics, str, Optional[str]]:
        prompt = task.render_prompt()
        start = perf_counter()
        status = "ok"
        failure_kind: Optional[str] = None
        error_message: Optional[str] = None
        response: Optional[ProviderResponse] = None
        try:
            response = provider.generate(prompt)
        except Exception as exc:  # pragma: no cover - 実プロバイダ利用時の防御
            status = "error"
            failure_kind = "provider_error"
            error_message = str(exc)
            latency_ms = int((perf_counter() - start) * 1000)
            response = ProviderResponse(output_text="", input_tokens=len(prompt.split()), output_tokens=0, latency_ms=latency_ms)
        latency_ms = response.latency_ms
        input_tokens = response.input_tokens
        output_tokens = response.output_tokens
        if (
            provider_config.timeout_s > 0
            and latency_ms > provider_config.timeout_s * 1000
            and status == "ok"
        ):
            status = "error"
            failure_kind = "timeout"
        cost_usd = compute_cost_usd(
            input_tokens,
            output_tokens,
            provider_config.pricing.prompt_usd,
            provider_config.pricing.completion_usd,
        )
        run_budget_limit = self.budget_manager.run_budget(provider_config.provider)
        run_budget_hit = run_budget_limit > 0 and cost_usd > run_budget_limit
        daily_stop_required = not self.budget_manager.notify_cost(
            provider_config.provider, cost_usd
        )
        budget_snapshot = BudgetSnapshot(
            run_budget_usd=run_budget_limit,
            hit_stop=run_budget_hit or daily_stop_required,
        )
        run_reason: Optional[str] = None
        if run_budget_hit:
            run_reason = (
                f"provider={provider_config.provider} run budget {run_budget_limit:.4f} USD exceeded "
                f"(cost={cost_usd:.4f} USD)"
            )
        daily_reason: Optional[str] = None
        if daily_stop_required:
            spent = self.budget_manager.spent_today(provider_config.provider)
            daily_limit = self.budget_manager.daily_budget(provider_config.provider)
            daily_reason = (
                f"provider={provider_config.provider} daily budget {daily_limit:.4f} USD exceeded "
                f"(spent={spent:.4f} USD)"
            )
        stop_reason: Optional[str] = None
        if not self.allow_overrun:
            if daily_reason:
                stop_reason = daily_reason
            elif self.budget_manager.should_stop_run(provider_config.provider, cost_usd):
                stop_reason = run_reason
        budget_messages = [msg for msg in (run_reason, daily_reason) if msg]
        if budget_messages:
            if status == "ok":
                status = "error"
            if failure_kind is None:
                failure_kind = "guard_violation"
            joined = " | ".join(budget_messages)
            if error_message:
                error_message = f"{error_message} | {joined}"
            else:
                error_message = joined
            if self.allow_overrun and stop_reason is None:
                LOGGER.warning("予算超過を許容 (--allow-overrun): %s", joined)
        output_text = response.output_text
        if (output_text is None or not output_text.strip()) and status == "ok":
            status = "error"
            failure_kind = "guard_violation"
        if not provider_config.persist_output:
            output_text_record: Optional[str] = None
        else:
            output_text_record = output_text
        output_hash = hash_text(output_text) if output_text else None
        eval_metrics, eval_failure_kind = self._evaluate(task, output_text)
        eval_metrics.len_tokens = output_tokens
        if eval_failure_kind and failure_kind is None:
            failure_kind = eval_failure_kind
        if eval_failure_kind and status == "ok":
            status = "error"
        ci_meta = self._ci_metadata()
        run_metrics = RunMetrics(
            ts=now_ts(),
            run_id=f"run_{task.task_id}_{attempt_index}_{uuid.uuid4().hex}",
            provider=provider_config.provider,
            model=provider_config.model,
            mode=mode,
            prompt_id=task.task_id,
            prompt_name=task.name,
            seed=provider_config.seed,
            temperature=provider_config.temperature,
            top_p=provider_config.top_p,
            max_tokens=provider_config.max_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            failure_kind=failure_kind,
            error_message=error_message,
            output_text=output_text_record,
            output_hash=output_hash,
            eval=eval_metrics,
            budget=budget_snapshot,
            ci_meta=ci_meta,
        )
        return run_metrics, output_text or "", stop_reason

    def _append_metric(self, metrics: RunMetrics) -> None:
        with self.metrics_path.open("a", encoding="utf-8") as fp:
            json.dump(metrics.to_json_dict(), fp, ensure_ascii=False)
            fp.write("\n")

    def _evaluate(self, task: GoldenTask, output_text: str) -> Tuple[EvalMetrics, Optional[str]]:
        expected_type = str(task.expected.get("type", "regex"))
        expected_value = task.expected.get("value")
        eval_metrics = EvalMetrics()
        failure_kind: Optional[str] = None
        if output_text is None:
            return eval_metrics, failure_kind
        if expected_type == "regex" and isinstance(expected_value, str):
            match = re.search(expected_value, output_text)
            eval_metrics.exact_match = bool(match)
            eval_metrics.diff_rate = 0.0 if match else 1.0
        elif expected_type == "literal" and isinstance(expected_value, str):
            eval_metrics.exact_match = output_text.strip() == expected_value.strip()
            eval_metrics.diff_rate = 0.0 if eval_metrics.exact_match else compute_diff_rate(
                output_text, expected_value
            )
        elif expected_type == "json_equal" and expected_value is not None:
            try:
                import json as _json

                actual = _json.loads(output_text)
                eval_metrics.exact_match = actual == expected_value
                eval_metrics.diff_rate = 0.0 if eval_metrics.exact_match else 1.0
            except Exception:
                eval_metrics.exact_match = False
                eval_metrics.diff_rate = 1.0
                failure_kind = "parsing"
        else:
            eval_metrics.diff_rate = 1.0
        return eval_metrics, failure_kind

    def _ci_metadata(self) -> Mapping[str, str]:
        meta = {}
        branch = os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_HEAD_REF")
        commit = os.getenv("GITHUB_SHA")
        if branch:
            meta["branch"] = branch
        if commit:
            meta["commit"] = commit
        return meta

    def _apply_determinism_gate(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        metrics_list: Sequence[RunMetrics],
        outputs: Sequence[str],
    ) -> None:
        gates = provider_config.quality_gates
        if gates.determinism_diff_rate_max <= 0 and gates.determinism_len_stdev_max <= 0:
            return
        comparable: List[Tuple[RunMetrics, str]] = [
            (metrics, output)
            for metrics, output in zip(metrics_list, outputs)
            if metrics.status == "ok" and output
        ]
        if len(comparable) < 2:
            return
        diff_rates: List[float] = []
        for idx, (_, output_a) in enumerate(comparable):
            for _, output_b in comparable[idx + 1 :]:
                diff_rates.append(compute_diff_rate(output_a, output_b))
        median_diff = median(diff_rates) if diff_rates else 0.0
        lengths: List[int] = [
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
