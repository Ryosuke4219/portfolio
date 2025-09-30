"""比較ランナーの実装。"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import re
from statistics import median, pstdev
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderResponse as JudgeProviderResponse
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import (  # type: ignore[import-not-found]
            ProviderResponse as JudgeProviderResponse,
        )
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        from dataclasses import dataclass
        from types import SimpleNamespace
        from typing import Any

        @dataclass(slots=True)
        class JudgeProviderResponse:
            text: str
            latency_ms: int
            tokens_in: int = 0
            tokens_out: int = 0
            raw: Any | None = None

            @property
            def token_usage(self) -> SimpleNamespace:
                return SimpleNamespace(
                    prompt=self.tokens_in,
                    completion=self.tokens_out,
                    total=self.tokens_in + self.tokens_out,
                )

from .aggregation_controller import AggregationController
from .budgets import BudgetManager
from .config import ProviderConfig
from .datasets import GoldenTask
from .metrics import (
    BudgetSnapshot,
    compute_diff_rate,
    EvalMetrics,
    hash_text,
    now_ts,
    RunMetrics,
)
from .providers import BaseProvider, ProviderFactory, ProviderResponse
from .runner_execution import (
    _SchemaValidator,
    _TokenBucket,
    RunnerExecution,
    SingleRunResult,
    run_parallel_any_sync,
)

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import RunnerConfig

LOGGER = logging.getLogger(__name__)

__all__ = ["CompareRunner", "run_parallel_any_sync"]


class _JudgeInvoker:
    def __init__(self, provider: BaseProvider, config: ProviderConfig) -> None:
        self._provider = provider
        self._config = config

    def invoke(self, request: object) -> JudgeProviderResponse:
        if hasattr(request, "prompt_text"):
            prompt = request.prompt_text or ""
        elif hasattr(request, "prompt"):
            prompt = request.prompt or ""
        else:
            prompt = ""
        response = self._provider.generate(prompt)
        return JudgeProviderResponse(
            text=response.output_text,
            latency_ms=response.latency_ms,
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            raw={"provider": self._config.provider},
        )


class _JudgeProviderFactoryAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def create(self, *, model: str) -> _JudgeInvoker:
        provider_config = replace(self._config, model=model)
        provider = ProviderFactory.create(provider_config)
        return _JudgeInvoker(provider, provider_config)


class CompareRunner:
    """プロバイダ横断でゴールデンタスクを評価する。"""

    def __init__(
        self,
        provider_configs: Sequence[ProviderConfig],
        tasks: Sequence[GoldenTask],
        budget_manager: BudgetManager,
        metrics_path: Path,
        allow_overrun: bool = False,
        runner_config: RunnerConfig | None = None,
        resolver: Callable[..., object] | None = None,
    ) -> None:
        self.provider_configs = list(provider_configs)
        self.tasks = list(tasks)
        self.budget_manager = budget_manager
        self.metrics_path = metrics_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.allow_overrun = allow_overrun
        self.runner_config = runner_config
        self.resolver = resolver  # 予約（現状未使用）

        self._schema_validator: _SchemaValidator | None = None
        self._token_bucket: _TokenBucket | None = None
        self._judge_provider_config: ProviderConfig | None = (
            runner_config.judge_provider if runner_config else None
        )
        self._aggregation = AggregationController(
            judge_factory_builder=lambda cfg: _JudgeProviderFactoryAdapter(cfg)
        )

    def run(self, repeat: int, config: RunnerConfig) -> list[RunMetrics]:
        repeat = max(repeat, 1)

        rpm = getattr(config, "rpm", None)
        self._token_bucket = _TokenBucket(rpm)

        schema_path = getattr(config, "schema", None)
        self._schema_validator = _SchemaValidator(schema_path)
        if config.judge_provider is not None:
            self._judge_provider_config = config.judge_provider

        execution = RunnerExecution(
            token_bucket=self._token_bucket,
            schema_validator=self._schema_validator,
            evaluate_budget=self._evaluate_budget,
            build_metrics=self._build_metrics,
            normalize_concurrency=self._normalize_concurrency,
        )

        providers: list[tuple[ProviderConfig, BaseProvider]] = []
        for provider_config in self.provider_configs:
            provider = ProviderFactory.create(provider_config)
            providers.append((provider_config, provider))
            LOGGER.info(
                "provider=%s model=%s を実行",
                provider_config.provider,
                provider_config.model,
            )

        results: list[RunMetrics] = []
        if not providers:
            return results

        stop_reason: str | None = None
        for task in self.tasks:
            histories: list[list[SingleRunResult]] = [[] for _ in providers]
            for attempt in range(repeat):
                if config.mode == "sequential":
                    batch, stop_reason = execution.run_sequential_attempt(
                        providers, task, attempt, config.mode
                    )
                else:
                    batch, stop_reason = execution.run_parallel_attempt(
                        providers, task, attempt, config
                    )
                self._aggregation.apply(
                    mode=config.mode,
                    config=config,
                    batch=batch,
                    default_judge_config=self._judge_provider_config,
                )
                for index, result in batch:
                    histories[index].append(result)
                if stop_reason:
                    break
            self._finalize_task(task, providers, histories, results)
            if stop_reason:
                LOGGER.warning("予算制約により実行を停止します: %s", stop_reason)
                break
        return results


    def _finalize_task(
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

    @staticmethod
    def _normalize_concurrency(total: int, limit: int | None) -> int:
        if total <= 0:
            return 1
        if limit is None or limit <= 0:
            return total
        return max(1, min(total, limit))

    def _build_metrics(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        attempt_index: int,
        mode: str,
        response: ProviderResponse,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
        latency_ms: int,
        budget_snapshot: BudgetSnapshot,
        cost_usd: float,
    ) -> tuple[RunMetrics, str]:
        output_text = response.output_text
        eval_metrics, eval_failure_kind = self._evaluate(task, output_text)
        eval_metrics.len_tokens = response.output_tokens
        status, failure_kind = self._merge_eval_failure(
            status, failure_kind, eval_failure_kind
        )
        output_text_record = output_text if provider_config.persist_output else None
        output_hash = self._compute_output_hash(output_text)
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
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            failure_kind=failure_kind,
            error_message=error_message,
            output_text=output_text_record,
            output_hash=output_hash,
            eval=eval_metrics,
            budget=budget_snapshot,
            ci_meta=self._ci_metadata(),
        )
        return run_metrics, output_text or ""

    def _merge_eval_failure(
        self,
        status: str,
        failure_kind: str | None,
        eval_failure_kind: str | None,
    ) -> tuple[str, str | None]:
        if not eval_failure_kind:
            return status, failure_kind
        failure_kind = failure_kind or eval_failure_kind
        if status == "ok":
            status = "error"
        return status, failure_kind

    def _compute_output_hash(self, output_text: str | None) -> str | None:
        return hash_text(output_text) if output_text else None

    def _evaluate_budget(
        self,
        provider_config: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        run_budget_limit = self.budget_manager.run_budget(provider_config.provider)
        run_budget_hit = run_budget_limit > 0 and cost_usd > run_budget_limit
        daily_stop_required = not self.budget_manager.notify_cost(
            provider_config.provider, cost_usd
        )
        budget_snapshot = BudgetSnapshot(
            run_budget_usd=run_budget_limit,
            hit_stop=run_budget_hit or daily_stop_required,
        )
        run_reason: str | None = None
        if run_budget_hit:
            run_reason = (
                f"provider={provider_config.provider} run budget "
                f"{run_budget_limit:.4f} USD exceeded "
                f"(cost={cost_usd:.4f} USD)"
            )
        daily_reason: str | None = None
        if daily_stop_required:
            spent = self.budget_manager.spent_today(provider_config.provider)
            daily_limit = self.budget_manager.daily_budget(provider_config.provider)
            daily_reason = (
                f"provider={provider_config.provider} daily budget "
                f"{daily_limit:.4f} USD exceeded "
                f"(spent={spent:.4f} USD)"
            )
        stop_reason: str | None = None
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
        return budget_snapshot, stop_reason, status, failure_kind, error_message

    def _append_metric(self, metrics: RunMetrics) -> None:
        with self.metrics_path.open("a", encoding="utf-8") as fp:
            json.dump(metrics.to_json_dict(), fp, ensure_ascii=False)
            fp.write("\n")

    def _evaluate(
        self, task: GoldenTask, output_text: str | None
    ) -> tuple[EvalMetrics, str | None]:
        expected_type = str(task.expected.get("type", "regex"))
        expected_value = task.expected.get("value")
        eval_metrics = EvalMetrics()
        failure_kind: str | None = None
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
        meta: dict[str, str] = {}
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
