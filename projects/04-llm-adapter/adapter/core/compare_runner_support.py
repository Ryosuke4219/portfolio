"""CompareRunner 用の補助クラス。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from enum import Enum
import logging
import os
import re
from typing import TYPE_CHECKING
import uuid

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
        class JudgeProviderResponse:  # type: ignore[too-many-ancestors]
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

LOGGER = logging.getLogger(__name__)

__all__ = [
    "RunMetricsBuilder",
    "BudgetEvaluator",
    "_JudgeInvoker",
    "_JudgeProviderFactoryAdapter",
]


class RunMetricsBuilder:
    """ランメトリクス生成ロジック。"""

    def build(
        self,
        provider_config: ProviderConfig,
        task: GoldenTask,
        attempt_index: int,
        mode: str | Enum,
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
        status, failure_kind = self._merge_eval_failure(status, failure_kind, eval_failure_kind)
        output_text_record = output_text if provider_config.persist_output else None
        output_hash = self._compute_output_hash(output_text)
        resolved_mode = mode.value if isinstance(mode, Enum) else mode
        canonical_mode = self._resolve_canonical_mode(mode, resolved_mode)
        run_metrics = RunMetrics(
            ts=now_ts(),
            run_id=f"run_{task.task_id}_{attempt_index}_{uuid.uuid4().hex}",
            provider=provider_config.provider,
            model=provider_config.model,
            mode=canonical_mode,
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
            cost_estimate=cost_usd,
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

    @staticmethod
    def _resolve_canonical_mode(mode: str | Enum, resolved_mode: object) -> str:
        """モード文字列を正規化する."""

        for candidate in (mode, resolved_mode):
            canonical = getattr(candidate, "canonical", None)
            if isinstance(canonical, str) and canonical:
                return canonical
        normalized = str(resolved_mode).strip().lower().replace("-", "_")
        return normalized

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

    def _evaluate(
        self,
        task: GoldenTask,
        output_text: str | None,
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
            eval_metrics.diff_rate = (
                0.0
                if eval_metrics.exact_match
                else compute_diff_rate(output_text, expected_value)
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

    @staticmethod
    def _compute_output_hash(output_text: str | None) -> str | None:
        return hash_text(output_text) if output_text else None

    @staticmethod
    def _ci_metadata() -> Mapping[str, str]:
        meta: dict[str, str] = {}
        branch = os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_HEAD_REF")
        commit = os.getenv("GITHUB_SHA")
        if branch:
            meta["branch"] = branch
        if commit:
            meta["commit"] = commit
        return meta


class BudgetEvaluator:
    """予算評価ロジック。"""

    def __init__(
        self,
        *,
        budget_manager: BudgetManager,
        allow_overrun: bool,
        logger: logging.Logger | None = None,
    ) -> None:
        self._budget_manager = budget_manager
        self.allow_overrun = allow_overrun
        self._logger = logger or LOGGER

    def evaluate(
        self,
        provider_config: ProviderConfig,
        cost_usd: float,
        status: str,
        failure_kind: str | None,
        error_message: str | None,
    ) -> tuple[BudgetSnapshot, str | None, str, str | None, str | None]:
        provider_name = provider_config.provider
        run_budget_limit = self._budget_manager.run_budget(provider_name)
        run_budget_hit = run_budget_limit > 0 and cost_usd > run_budget_limit
        daily_stop_required = not self._budget_manager.notify_cost(provider_name, cost_usd)
        budget_snapshot = BudgetSnapshot(
            run_budget_usd=run_budget_limit,
            hit_stop=run_budget_hit or daily_stop_required,
        )
        run_reason: str | None = None
        if run_budget_hit:
            run_reason = (
                f"provider={provider_name} run budget {run_budget_limit:.4f} USD exceeded "
                f"(cost={cost_usd:.4f} USD)"
            )
        daily_reason: str | None = None
        if daily_stop_required:
            spent = self._budget_manager.spent_today(provider_name)
            daily_limit = self._budget_manager.daily_budget(provider_name)
            daily_reason = (
                f"provider={provider_name} daily budget {daily_limit:.4f} USD exceeded "
                f"(spent={spent:.4f} USD)"
            )
        stop_reason: str | None = None
        if not self.allow_overrun:
            if daily_reason:
                stop_reason = daily_reason
            elif self._budget_manager.should_stop_run(provider_name, cost_usd):
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
                self._logger.warning("予算超過を許容 (--allow-overrun): %s", joined)
        return budget_snapshot, stop_reason, status, failure_kind, error_message


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
