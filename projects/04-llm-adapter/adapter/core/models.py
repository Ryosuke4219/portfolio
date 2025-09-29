"""設定モデルの dataclass 定義。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "RetryConfig",
    "PricingConfig",
    "RateLimitConfig",
    "QualityGatesConfig",
    "ProviderConfig",
    "BudgetRule",
    "BudgetBook",
]


@dataclass
class RetryConfig:
    """API 呼び出しの再試行設定。"""

    max: int = 0
    backoff_s: float = 0.0


@dataclass
class PricingConfig:
    """1k トークンあたりの料金設定。"""

    prompt_usd: float = 0.0
    completion_usd: float = 0.0
    input_per_million: float = 0.0
    output_per_million: float = 0.0


@dataclass
class RateLimitConfig:
    """レートリミットのしきい値。"""

    rpm: int = 0
    tpm: int = 0


@dataclass
class QualityGatesConfig:
    """決定性ゲートのしきい値。"""

    determinism_diff_rate_max: float = 0.0
    determinism_len_stdev_max: float = 0.0


@dataclass
class ProviderConfig:
    """プロバイダ設定。"""

    path: Path
    schema_version: int | None
    provider: str
    endpoint: str | None
    model: str
    auth_env: str | None
    seed: int
    temperature: float
    top_p: float
    max_tokens: int
    timeout_s: int
    retries: RetryConfig
    persist_output: bool
    pricing: PricingConfig
    rate_limit: RateLimitConfig
    quality_gates: QualityGatesConfig
    raw: Mapping[str, Any]


@dataclass
class BudgetRule:
    """プロバイダごとの予算ルール。"""

    run_budget_usd: float
    daily_budget_usd: float
    stop_on_budget_exceed: bool


@dataclass
class BudgetBook:
    """予算設定全体。"""

    default: BudgetRule
    overrides: Mapping[str, BudgetRule]
