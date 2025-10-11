"""Shadow shim delegating to the core implementation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CORE_SUPPORT = (
    Path(__file__).resolve().parents[2].parent
    / "04-llm-adapter"
    / "adapter"
    / "core"
    / "runner_async_support"
    / "__init__.py"
)

_spec = importlib.util.spec_from_file_location("_core_runner_async_support", _CORE_SUPPORT)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise ImportError("adapter.core.runner_async_support module is unavailable")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
sys.modules[__name__] = _module
