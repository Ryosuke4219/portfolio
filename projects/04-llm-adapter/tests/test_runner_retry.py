from __future__ import annotations

# NOTE: Legacy shim for runner retry tests.
# Checklist:
# - [ ] 04-llm-adapter tests import modules from projects/04-llm-adapter/tests/runner_retry
# - [ ] Remove this shim once all references are updated
from .runner_retry import test_rate_limit_failover as _test_rate_limit_failover, test_shadow_metrics as _test_shadow_metrics
from .runner_retry.test_rate_limit_failover import *  # noqa: F401,F403
from .runner_retry.test_shadow_metrics import *  # noqa: F401,F403

__all__ = (
    _test_rate_limit_failover.__all__
    + _test_shadow_metrics.__all__
)
