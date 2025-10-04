"""compare_runner_support パッケージ。"""
from __future__ import annotations

from importlib import util
from pathlib import Path
import sys

from .metrics_builder import RunMetricsBuilder

_LEGACY_PATH = Path(__file__).resolve().parent.parent / "compare_runner_support.py"
_LEGACY_SPEC = util.spec_from_file_location(
    "adapter.core._compare_runner_support_legacy",
    _LEGACY_PATH,
)
if _LEGACY_SPEC is None or _LEGACY_SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError("compare_runner_support legacy module could not be loaded")

_LEGACY_MODULE = util.module_from_spec(_LEGACY_SPEC)
sys.modules[_LEGACY_SPEC.name] = _LEGACY_MODULE
_LEGACY_SPEC.loader.exec_module(_LEGACY_MODULE)

BudgetEvaluator = _LEGACY_MODULE.BudgetEvaluator
_JudgeInvoker = _LEGACY_MODULE._JudgeInvoker
_JudgeProviderFactoryAdapter = _LEGACY_MODULE._JudgeProviderFactoryAdapter

__all__ = [
    "RunMetricsBuilder",
    "BudgetEvaluator",
    "_JudgeInvoker",
    "_JudgeProviderFactoryAdapter",
]
