from __future__ import annotations

from .test_parallel_all import *  # noqa: F401,F403
from .test_parallel_any_failures import *  # noqa: F401,F403
from .test_parallel_any_metrics import *  # noqa: F401,F403

__all__ = []
__all__ += [name for name in globals() if name.startswith("test_")]
