"""Compatibility re-export for adapter core error hierarchy."""
from __future__ import annotations

from adapter.core import errors as _core_errors

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
