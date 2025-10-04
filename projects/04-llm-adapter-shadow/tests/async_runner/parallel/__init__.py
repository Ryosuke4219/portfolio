from __future__ import annotations

from src.llm_adapter.runner import ParallelAllResult as _ParallelAllResult

from .test_parallel_all import *  # noqa: F401,F403
from .test_parallel_any_failures import *  # noqa: F401,F403
from .test_parallel_any_metrics import *  # noqa: F401,F403

ParallelAllResult = _ParallelAllResult

__all__ = ["ParallelAllResult"]
__all__ += [name for name in globals() if name.startswith("test_")]
