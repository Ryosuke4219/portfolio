"""CompareRunner 用の補助クラス。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import logging
from typing import Any

from .budgets import BudgetManager
from .compare_runner_support.metrics_builder import RunMetricsBuilder
from .config import ProviderConfig
from .metrics.models import BudgetSnapshot
from .provider_spi import ProviderRequest, TokenUsage
from .providers import (
    BaseProvider,
    ProviderFactory,
    ProviderResponse,
)

JudgeProviderResponse = ProviderResponse

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
            joined = " | ".join(budget_messages)
            if self.allow_overrun and stop_reason is None:
                self._logger.warning("予算超過を許容 (--allow-overrun): %s", joined)
            else:
                if status == "ok":
                    status = "error"
                if failure_kind is None:
                    failure_kind = "guard_violation"
                if error_message:
                    error_message = f"{error_message} | {joined}"
                else:
                    error_message = joined
        return budget_snapshot, stop_reason, status, failure_kind, error_message


class _JudgeInvoker:
    def __init__(self, provider: BaseProvider, config: ProviderConfig) -> None:
        self._provider = provider
        self._config = config

    def invoke(self, request: object) -> JudgeProviderResponse:
        provider_request = self._build_provider_request(request)
        response = self._provider.invoke(provider_request)
        base_response = _coerce_provider_response(response)
        raw_payload = _merge_raw_payload(base_response.raw, self._config.provider)
        return JudgeProviderResponse(
            text=base_response.text,
            latency_ms=base_response.latency_ms,
            token_usage=base_response.token_usage,
            model=base_response.model,
            finish_reason=base_response.finish_reason,
            raw=raw_payload,
        )

    def _build_provider_request(self, request: object) -> ProviderRequest:
        if isinstance(request, ProviderRequest):
            return request

        prompt = self._extract_prompt(request)
        model = (self._config.model or self._config.provider).strip() or self._config.provider
        timeout: float | None = None
        if self._config.timeout_s > 0:
            timeout = float(self._config.timeout_s)
        raw_config = self._config.raw
        options_source = raw_config.get("options") if isinstance(raw_config, Mapping) else None
        metadata_source = raw_config.get("metadata") if isinstance(raw_config, Mapping) else None
        options: dict[str, Any] = {}
        if isinstance(options_source, Mapping):
            options = dict(options_source)
        metadata: Mapping[str, Any] | None = None
        if isinstance(metadata_source, Mapping):
            metadata = dict(metadata_source)
        return ProviderRequest(
            model=model,
            prompt=prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            top_p=self._config.top_p,
            timeout_s=timeout,
            options=options,
            metadata=metadata,
        )

    @staticmethod
    def _extract_prompt(request: object) -> str:
        prompt = ""
        if isinstance(request, Mapping):
            mapping_value = request.get("text")
            if isinstance(mapping_value, str):
                prompt = mapping_value
            else:
                mapping_value = request.get("prompt")
                if isinstance(mapping_value, str):
                    prompt = mapping_value
        if not prompt:
            if hasattr(request, "prompt_text"):
                prompt = request.prompt_text or ""
            elif hasattr(request, "prompt"):
                prompt = request.prompt or ""
        return prompt


class _JudgeProviderFactoryAdapter:
    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def create(self, *, model: str) -> _JudgeInvoker:
        provider_config = replace(self._config, model=model)
        provider = ProviderFactory.create(provider_config)
        return _JudgeInvoker(provider, provider_config)


def _coerce_provider_response(response: object) -> ProviderResponse:
    if isinstance(response, ProviderResponse):
        return response

    text = getattr(response, "text", None)
    if not isinstance(text, str):
        text = getattr(response, "output_text", "")
    if not isinstance(text, str):
        text = str(text)

    latency = getattr(response, "latency_ms", 0)
    try:
        latency_ms = int(latency)
    except (TypeError, ValueError):
        latency_ms = 0

    token_usage = getattr(response, "token_usage", None)
    if not isinstance(token_usage, TokenUsage):
        tokens_in = getattr(response, "tokens_in", getattr(response, "input_tokens", 0))
        tokens_out = getattr(response, "tokens_out", getattr(response, "output_tokens", 0))
        token_usage = TokenUsage(
            prompt=int(tokens_in or 0),
            completion=int(tokens_out or 0),
        )

    model = getattr(response, "model", None)
    model_value = model if isinstance(model, str) else None

    finish_reason = getattr(response, "finish_reason", None)
    finish_value = finish_reason if isinstance(finish_reason, str) else None

    raw = getattr(response, "raw", None)

    return ProviderResponse(
        text=text,
        latency_ms=latency_ms,
        token_usage=token_usage,
        model=model_value,
        finish_reason=finish_value,
        raw=raw,
    )


def _merge_raw_payload(raw: Any, provider_name: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"provider": provider_name}
    if isinstance(raw, Mapping):
        payload.update(raw)
    elif raw is not None:
        payload["payload"] = raw
    return payload
