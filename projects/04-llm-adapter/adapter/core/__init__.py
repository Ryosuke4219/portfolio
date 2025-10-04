"""adapter.core パッケージの公開 API。"""

from .aggregation import (  # noqa: F401
    AggregationCandidate,
    AggregationResolver,
    AggregationResult,
    AggregationStrategy,
    FirstTieBreaker,
    JudgeStrategy,
    MajorityVoteStrategy,
    MaxScoreStrategy,
    MaxScoreTieBreaker,
)
from .budgets import BudgetManager  # noqa: F401
from .config import (  # noqa: F401
    BudgetBook,
    BudgetRule,
    load_budget_book,
    load_provider_config,
    load_provider_configs,
    ProviderConfig,
)
from .datasets import GoldenTask, load_golden_tasks  # noqa: F401
from .metrics.costs import compute_cost_usd, estimate_cost  # noqa: F401
from .metrics.diff import compute_diff_rate  # noqa: F401
from .metrics.models import (  # noqa: F401
    BudgetSnapshot,
    EvalMetrics,
    RunMetric,
    RunMetrics,
    hash_text,
    now_ts,
)
from .providers import ProviderFactory  # noqa: F401
from .runners import CompareRunner  # noqa: F401

__all__ = [
    "AggregationCandidate",
    "AggregationResolver",
    "AggregationResult",
    "AggregationStrategy",
    "FirstTieBreaker",
    "JudgeStrategy",
    "BudgetManager",
    "BudgetBook",
    "BudgetRule",
    "ProviderConfig",
    "load_budget_book",
    "load_provider_config",
    "load_provider_configs",
    "GoldenTask",
    "load_golden_tasks",
    "BudgetSnapshot",
    "EvalMetrics",
    "RunMetric",
    "RunMetrics",
    "compute_cost_usd",
    "compute_diff_rate",
    "estimate_cost",
    "hash_text",
    "now_ts",
    "MajorityVoteStrategy",
    "MaxScoreStrategy",
    "MaxScoreTieBreaker",
    "ProviderFactory",
    "CompareRunner",
]
