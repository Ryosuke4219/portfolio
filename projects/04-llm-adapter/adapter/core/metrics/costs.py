"""コスト計算ユーティリティ。"""

from __future__ import annotations

from typing import TYPE_CHECKING


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


def estimate_cost(config: "ProviderConfig", input_tokens: int, output_tokens: int) -> float:
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


if TYPE_CHECKING:  # pragma: no cover - 循環参照の回避
    from ..config import ProviderConfig
