# ruff: noqa: I001

from __future__ import annotations

import sys

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHADOW_ROOT = PROJECT_ROOT.parent / "04-llm-adapter-shadow"


def ensure_import_paths() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    if SHADOW_ROOT.exists() and str(SHADOW_ROOT) not in sys.path:
        sys.path.insert(0, str(SHADOW_ROOT))


ensure_import_paths()


BudgetManager: Any
GoldenTask: Any
PricingConfig: Any
ProviderConfig: Any
QualityGatesConfig: Any
RateLimitConfig: Any
RetryConfig: Any
RunMetrics: Any


def __getattr__(name: str) -> Any:
    if name == "BudgetManager":
        from adapter.core.budgets import BudgetManager as _BudgetManager

        globals()[name] = _BudgetManager
        return _BudgetManager
    if name == "GoldenTask":
        from adapter.core.datasets import GoldenTask as _GoldenTask

        globals()[name] = _GoldenTask
        return _GoldenTask
    if name == "RunMetrics":
        from adapter.core.metrics import RunMetrics as _RunMetrics

        globals()[name] = _RunMetrics
        return _RunMetrics
    if name == "ProviderConfig":
        from adapter.core.models import ProviderConfig as _ProviderConfig

        globals()[name] = _ProviderConfig
        return _ProviderConfig
    if name == "PricingConfig":
        from adapter.core.models import PricingConfig as _PricingConfig

        globals()[name] = _PricingConfig
        return _PricingConfig
    if name == "QualityGatesConfig":
        from adapter.core.models import QualityGatesConfig as _QualityGatesConfig

        globals()[name] = _QualityGatesConfig
        return _QualityGatesConfig
    if name == "RateLimitConfig":
        from adapter.core.models import RateLimitConfig as _RateLimitConfig

        globals()[name] = _RateLimitConfig
        return _RateLimitConfig
    if name == "RetryConfig":
        from adapter.core.models import RetryConfig as _RetryConfig

        globals()[name] = _RetryConfig
        return _RetryConfig
    raise AttributeError(name)


__all__ = [
    "BudgetManager",
    "GoldenTask",
    "PricingConfig",
    "ProviderConfig",
    "QualityGatesConfig",
    "RateLimitConfig",
    "RetryConfig",
    "RunMetrics",
    "ensure_import_paths",
]
