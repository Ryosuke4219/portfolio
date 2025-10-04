"""Legacy compatibility shim for sequential runner tests.

Tests now live under projects/04-llm-adapter-shadow/tests/sequential/.
Checklist before removing this shim:
- [ ] Update direct imports to use the new modules.
- [ ] Ensure downstream tooling no longer relies on this file path.
- [ ] Confirm pytest runs succeed without importing this module.
Remove this file once all items are checked.
"""

# Legacy compatibility shim for sequential runner tests.
# Tests now live under projects/04-llm-adapter-shadow/tests/sequential/.
# Checklist before removing this shim:
# - [ ] Update direct imports to use the new modules.
# - [ ] Ensure downstream tooling no longer relies on this file path.
# - [ ] Confirm pytest runs succeed without importing this module.
# Remove this file once all items are checked.
from __future__ import annotations

from .sequential.test_failures import *  # noqa: F401,F403
from .sequential.test_fallback_events import *  # noqa: F401,F403
from .sequential.test_metrics import *  # noqa: F401,F403
