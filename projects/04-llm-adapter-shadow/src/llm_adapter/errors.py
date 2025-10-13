"""Compatibility re-export for adapter core error hierarchy."""
from __future__ import annotations

from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

try:
    _core_errors = import_module("adapter.core.errors")
except ModuleNotFoundError as exc:  # pragma: no cover - adapter shim fallback
    _shadow_root = Path(__file__).resolve().parents[2]
    _adapter_core_errors = (
        _shadow_root.parent / "04-llm-adapter" / "adapter" / "core" / "errors.py"
    )
    _spec = spec_from_file_location("adapter.core.errors", _adapter_core_errors)
    if _spec is None or _spec.loader is None:
        raise ImportError("adapter.core.errors をロードできません") from exc
    _fallback_module = module_from_spec(_spec)
    sys.modules.setdefault("adapter.core.errors", _fallback_module)
    _spec.loader.exec_module(_fallback_module)
    _core_errors = _fallback_module

AdapterError = _core_errors.AdapterError
RetryableError = _core_errors.RetryableError
SkipError = _core_errors.SkipError
FatalError = _core_errors.FatalError
TimeoutError = _core_errors.TimeoutError
RateLimitError = _core_errors.RateLimitError
AuthError = _core_errors.AuthError
RetriableError = _core_errors.RetriableError
ProviderSkip = _core_errors.ProviderSkip
SkipReason = _core_errors.SkipReason
ConfigError = _core_errors.ConfigError
AllFailedError = _core_errors.AllFailedError
ParallelExecutionError = _core_errors.ParallelExecutionError

__all__ = _core_errors.__all__
