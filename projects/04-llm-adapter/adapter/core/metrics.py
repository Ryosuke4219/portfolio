"""メトリクス関連ユーティリティ。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


@dataclass
class EvalMetrics:
    """評価結果。"""

    exact_match: Optional[bool] = None
    diff_rate: Optional[float] = None
    len_tokens: Optional[int] = None


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
    failure_kind: Optional[str]
    error_message: Optional[str]
    output_text: Optional[str]
    output_hash: Optional[str]
    eval: EvalMetrics = field(default_factory=EvalMetrics)
    budget: BudgetSnapshot = field(default_factory=lambda: BudgetSnapshot(0.0, False))
    ci_meta: Mapping[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["eval"] = {k: v for k, v in payload["eval"].items() if v is not None}
        return payload


def now_ts() -> str:
    """UTC ISO 時刻を返す。"""

    return datetime.now(timezone.utc).isoformat()


def hash_text(text: str) -> str:
    """SHA-256 ハッシュを `sha256:...` 形式で返す。"""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_cost_usd(prompt_tokens: int, completion_tokens: int, prompt_price: float, completion_price: float) -> float:
    """トークン数と単価からコストを算出する。"""

    prompt_cost = (prompt_tokens / 1000.0) * prompt_price
    completion_cost = (completion_tokens / 1000.0) * completion_price
    return round(prompt_cost + completion_cost, 6)


def tokenize(text: str) -> List[str]:
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
