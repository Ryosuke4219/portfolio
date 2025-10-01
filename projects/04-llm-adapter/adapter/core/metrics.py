"""メトリクス関連ユーティリティ。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
import hashlib
import math
from statistics import median
from typing import Any, Literal, Protocol, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - 循環参照の回避
    from .config import ProviderConfig
    from .execution.shadow_runner import ShadowRunnerResult
    from .providers import ProviderResponse


class RunMetric(BaseModel):
    """シンプルなランメトリクス表現。"""

    provider: str
    model: str
    endpoint: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0
    status: str = "ok"
    error: str | None = None
    prompt_sha256: str = Field(..., description="content hash without secrets")

    @classmethod
    def from_resp(
        cls,
        cfg: ProviderConfig,
        resp: ProviderResponse,
        prompt: str,
        *,
        cost_usd: float = 0.0,
        error: str | None = None,
    ) -> RunMetric:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return cls(
            provider=cfg.provider,
            model=cfg.model,
            endpoint=(cfg.endpoint or "responses"),
            latency_ms=int(resp.latency_ms),
            input_tokens=int(resp.input_tokens),
            output_tokens=int(resp.output_tokens),
            cost_usd=float(cost_usd),
            status="error" if error else "ok",
            error=error,
            prompt_sha256=digest,
        )


@dataclass
class EvalMetrics:
    """評価結果。"""

    exact_match: bool | None = None
    diff_rate: float | None = None
    len_tokens: int | None = None


@dataclass
class BudgetSnapshot:
    """予算情報。"""

    run_budget_usd: float
    hit_stop: bool


@dataclass
class RunMetrics:
    """JSONL へ書き出す 1 行のメトリクス。"""

    ts: str
    run_id: str
    provider: str
    model: str
    mode: str
    prompt_id: str
    prompt_name: str
    seed: int
    temperature: float
    top_p: float
    max_tokens: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    status: str
    failure_kind: str | None
    error_message: str | None
    output_text: str | None
    output_hash: str | None
    error_type: str | None = None
    providers: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    attempts: int = 0
    retries: int = 0
    outcome: Literal["success", "skip", "error"] = "success"
    shadow_provider_id: str | None = None
    shadow_latency_ms: int | None = None
    shadow_status: str | None = None
    shadow_error_message: str | None = None
    shadow_outcome: Literal["success", "skip", "error"] | None = None
    eval: EvalMetrics = field(default_factory=EvalMetrics)
    budget: BudgetSnapshot = field(default_factory=lambda: BudgetSnapshot(0.0, False))
    ci_meta: Mapping[str, Any] = field(default_factory=dict)
    cost_estimate: float = field(default=float("nan"))

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = asdict(self)
        payload["eval"] = {k: v for k, v in payload["eval"].items() if v is not None}
        payload["cost_usd"] = float(self.cost_usd)
        payload["cost_estimate"] = float(self.cost_estimate)
        return payload

    def __post_init__(self) -> None:
        cost_usd = float(self.cost_usd)
        try:
            estimate = float(self.cost_estimate)
        except (TypeError, ValueError):
            estimate = cost_usd
        if math.isnan(estimate):
            estimate = cost_usd
        self.cost_usd = cost_usd
        self.cost_estimate = estimate


class ProviderCallResult(Protocol):
    error: Exception | None
    retries: int


def finalize_run_metrics(
    run_metrics: RunMetrics,
    *,
    attempt_index: int,
    provider_result: ProviderCallResult,
    response: ProviderResponse,
    status: str,
    failure_kind: str | None,
    error_message: str | None,
    schema_error: str | None,
    shadow_result: ShadowRunnerResult | None,
    fallback_shadow_id: str | None,
    active_provider_ids: Sequence[str],
    current_attempt_index: int,
) -> None:
    provider_ids: list[str] = []
    for provider_id in active_provider_ids:
        if provider_id not in provider_ids:
            provider_ids.append(provider_id)
    run_metrics.providers = provider_ids
    usage = response.token_usage
    prompt_tokens = int(getattr(usage, "prompt", response.input_tokens))
    completion_tokens = int(getattr(usage, "completion", response.output_tokens))
    total_tokens = int(getattr(usage, "total", prompt_tokens + completion_tokens))
    run_metrics.token_usage = {
        "prompt": prompt_tokens,
        "completion": completion_tokens,
        "total": total_tokens,
    }
    run_metrics.attempts = attempt_index + 1
    run_metrics.error_type = (
        type(provider_result.error).__name__ if provider_result.error else None
    )
    run_metrics.retries = max(current_attempt_index, 0) + max(
        provider_result.retries - 1, 0
    )
    if schema_error:
        run_metrics.status = status
        run_metrics.failure_kind = failure_kind
        run_metrics.error_message = error_message
    run_metrics.outcome = _resolve_outcome(run_metrics.status)
    apply_shadow_metrics(run_metrics, shadow_result, fallback_shadow_id)


def apply_shadow_metrics(
    run_metrics: RunMetrics,
    shadow_result: ShadowRunnerResult | None,
    fallback_shadow_id: str | None,
) -> None:
    if shadow_result is None:
        if fallback_shadow_id is not None:
            run_metrics.shadow_provider_id = fallback_shadow_id
        return
    provider_id = shadow_result.provider_id or fallback_shadow_id
    if provider_id is not None:
        run_metrics.shadow_provider_id = provider_id
    if shadow_result.latency_ms is not None:
        run_metrics.shadow_latency_ms = int(shadow_result.latency_ms)
    if shadow_result.status is not None:
        run_metrics.shadow_status = shadow_result.status
        run_metrics.shadow_outcome = _resolve_outcome(shadow_result.status)
    if shadow_result.error_message is not None:
        run_metrics.shadow_error_message = shadow_result.error_message


def _resolve_outcome(status: str) -> Literal["success", "skip", "error"]:
    if status == "ok":
        return "success"
    if status == "skip":
        return "skip"
    return "error"


def now_ts() -> str:
    """UTC ISO 時刻を返す。"""

    return datetime.now(UTC).isoformat()


def hash_text(text: str) -> str:
    """SHA-256 ハッシュを `sha256:...` 形式で返す。"""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _cost_for_tokens(tokens: int, price_per_thousand: float) -> float:
    return (tokens / 1000.0) * price_per_thousand


def compute_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    prompt_price: float,
    completion_price: float,
) -> float:
    """トークン数と単価からコストを算出する。"""

    prompt_cost = _cost_for_tokens(prompt_tokens, prompt_price)
    completion_cost = _cost_for_tokens(completion_tokens, completion_price)
    return round(prompt_cost + completion_cost, 6)


def estimate_cost(config: ProviderConfig, input_tokens: int, output_tokens: int) -> float:
    """プロバイダ設定に基づいて概算コストを算出する。"""

    pricing = config.pricing
    input_per_million = float(pricing.input_per_million or 0.0)
    output_per_million = float(pricing.output_per_million or 0.0)
    if input_per_million or output_per_million:
        cost = (input_tokens / 1_000_000.0) * input_per_million
        cost += (output_tokens / 1_000_000.0) * output_per_million
        return round(cost, 6)
    prompt_price = float(pricing.prompt_usd or 0.0)
    completion_price = float(pricing.completion_usd or 0.0)
    return compute_cost_usd(input_tokens, output_tokens, prompt_price, completion_price)


def tokenize(text: str) -> list[str]:
    """簡易トークン化。"""

    return text.split()


def levenshtein_distance(a: Sequence[str], b: Sequence[str]) -> int:
    """レーベンシュタイン距離。"""

    if not a:
        return len(b)
    if not b:
        return len(a)
    prev_row = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current_row = [i]
        for j, token_b in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = prev_row[j] + 1
            replace_cost = prev_row[j - 1] + (0 if token_a == token_b else 1)
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        prev_row = current_row
    return prev_row[-1]


def compute_diff_rate(output_a: str, output_b: str) -> float:
    """差分率を 0..1 で返す。"""

    tokens_a = tokenize(output_a)
    tokens_b = tokenize(output_b)
    if not tokens_a and not tokens_b:
        return 0.0
    distance = levenshtein_distance(tokens_a, tokens_b)
    return distance / max(len(tokens_a), len(tokens_b))


def summarize_diff_rates(diff_rates: Iterable[float]) -> float:
    """中央値を返す。空の場合は 0。"""

    data = list(diff_rates)
    if not data:
        return 0.0
    return float(median(data))
