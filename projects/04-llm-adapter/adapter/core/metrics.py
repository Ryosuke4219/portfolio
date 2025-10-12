"""メトリクス関連ユーティリティのレガシー互換シム。"""

# このファイルは分割済みモジュールへの案内用（チェックリスト完了で削除）
# - [ ] adapter.core.metrics.models を直接 import している
# - [ ] adapter.core.metrics.update を直接 import している
# - [ ] adapter.core.metrics.costs を直接 import している
# - [ ] adapter.core.metrics.diff を直接 import している

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
import sys


def _load_submodule(module_name: str) -> ModuleType:
    qualified_name = f"{__name__}.{module_name}"
    module_path = Path(__file__).with_name("metrics") / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified_name, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - importguard
        raise ModuleNotFoundError(qualified_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module


_models = _load_submodule("models")
_update = _load_submodule("update")
_costs = _load_submodule("costs")
_diff = _load_submodule("diff")

sys.modules[f"{__name__}.models"] = _models
sys.modules[f"{__name__}.update"] = _update
sys.modules[f"{__name__}.costs"] = _costs
sys.modules[f"{__name__}.diff"] = _diff

RunMetric = _models.RunMetric
RunMetrics = _models.RunMetrics
EvalMetrics = _models.EvalMetrics
BudgetSnapshot = _models.BudgetSnapshot
now_ts = _models.now_ts
hash_text = _models.hash_text

finalize_run_metrics = _update.finalize_run_metrics
apply_shadow_metrics = _update.apply_shadow_metrics
ProviderCallResult = _update.ProviderCallResult

compute_cost_usd = _costs.compute_cost_usd
estimate_cost = _costs.estimate_cost

tokenize = _diff.tokenize
levenshtein_distance = _diff.levenshtein_distance
compute_diff_rate = _diff.compute_diff_rate
summarize_diff_rates = _diff.summarize_diff_rates

__all__ = [
    "RunMetric",
    "RunMetrics",
    "EvalMetrics",
    "BudgetSnapshot",
    "now_ts",
    "hash_text",
    "finalize_run_metrics",
    "apply_shadow_metrics",
    "ProviderCallResult",
    "compute_cost_usd",
    "estimate_cost",
    "tokenize",
    "levenshtein_distance",
    "compute_diff_rate",
    "summarize_diff_rates",
]

