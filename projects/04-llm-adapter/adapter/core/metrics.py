"""メトリクス関連ユーティリティ。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
import hashlib
from statistics import median
from typing import Any, Literal, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - 循環参照の回避
    from .config import ProviderConfig
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
    providers: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    outcome: Literal["success", "skip", "error"] = "success"
    eval: EvalMetrics = field(default_factory=EvalMetrics)
    budget: BudgetSnapshot = field(default_factory=lambda: BudgetSnapshot(0.0, False))
    ci_meta: Mapping[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = asdict(self)
        payload["eval"] = {k: v for k, v in payload["eval"].items() if v is not None}
        return payload


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
