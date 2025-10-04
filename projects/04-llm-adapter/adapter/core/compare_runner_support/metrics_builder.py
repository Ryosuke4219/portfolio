"""RunMetricsBuilder 専用モジュール。"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import os
import re
import uuid
from ..config import ProviderConfig
from ..datasets import GoldenTask
from ..metrics.diff import compute_diff_rate
from ..metrics.models import BudgetSnapshot, EvalMetrics, RunMetrics, hash_text, now_ts
from ..providers import ProviderResponse


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
