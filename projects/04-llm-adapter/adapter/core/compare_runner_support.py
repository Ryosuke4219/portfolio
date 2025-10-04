"""CompareRunner 用の補助クラス。"""
from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from .budgets import BudgetManager
from .config import ProviderConfig
from .metrics.models import BudgetSnapshot
from .providers import BaseProvider, ProviderFactory, ProviderResponse
from .compare_runner_support.metrics_builder import RunMetricsBuilder

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
