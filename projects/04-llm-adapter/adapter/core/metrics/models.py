"""メトリクスのモデルおよびシリアライズ関連。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
import hashlib
from typing import Any, Literal, TYPE_CHECKING

from pydantic import BaseModel, Field


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
    cost_estimate: float | None = None

    def __post_init__(self) -> None:
        if self.cost_estimate is None:
            self.cost_estimate = self.cost_usd

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = asdict(self)
        payload["cost_estimate"] = (
            self.cost_estimate if self.cost_estimate is not None else self.cost_usd
        )
        payload["eval"] = {k: v for k, v in payload["eval"].items() if v is not None}
        return payload


def now_ts() -> str:
    """UTC ISO 時刻を返す。"""

    return datetime.now(UTC).isoformat()


def hash_text(text: str) -> str:
    """SHA-256 ハッシュを `sha256:...` 形式で返す。"""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


if TYPE_CHECKING:  # pragma: no cover - 型チェック用
    from ..config import ProviderConfig
    from ..providers import ProviderResponse
