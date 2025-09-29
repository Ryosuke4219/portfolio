"""設定ファイル検証用の Pydantic モデル。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RetryConfigModel",
    "PricingConfigModel",
    "RateLimitConfigModel",
    "QualityGatesConfigModel",
    "ProviderConfigModel",
]


class RetryConfigModel(BaseModel):
    """API 呼び出し再試行設定のスキーマ。"""

    model_config = ConfigDict(extra="forbid")

    max: int = 0
    backoff_s: float = 0.0


class PricingConfigModel(BaseModel):
    """料金設定のスキーマ。"""

    model_config = ConfigDict(extra="forbid")

    prompt_usd: float = 0.0
    completion_usd: float = 0.0
    input_per_million: float = 0.0
    output_per_million: float = 0.0


class RateLimitConfigModel(BaseModel):
    """レートリミット設定のスキーマ。"""

    model_config = ConfigDict(extra="forbid")

    rpm: int = 0
    tpm: int = 0


class QualityGatesConfigModel(BaseModel):
    """決定性ゲート設定のスキーマ。"""

    model_config = ConfigDict(extra="forbid")

    determinism_diff_rate_max: float = 0.0
    determinism_len_stdev_max: float = 0.0


class ProviderConfigModel(BaseModel):
    """プロバイダ設定全体のスキーマ。"""

    model_config = ConfigDict(extra="allow")

    schema_version: int | None = None
    provider: str
    endpoint: str | None = None
    model: str
    auth_env: str | None = None
    seed: int = 0
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 0
    timeout_s: int = 0
    retries: RetryConfigModel = Field(default_factory=RetryConfigModel)
    persist_output: bool = False
    pricing: PricingConfigModel = Field(default_factory=PricingConfigModel)
    rate_limit: RateLimitConfigModel = Field(default_factory=RateLimitConfigModel)
    quality_gates: QualityGatesConfigModel = Field(default_factory=QualityGatesConfigModel)
