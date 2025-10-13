from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_shadow_module() -> object:
    repo_root = Path(__file__).resolve().parents[2]
    module_path = (
        repo_root / "projects" / "04-llm-adapter-shadow" / "src" / "llm_adapter" / "errors.py"
    )
    spec = importlib.util.spec_from_file_location("llm_adapter.errors", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "symbol",
    [
        "AdapterError",
        "RetryableError",
        "SkipError",
        "FatalError",
        "TimeoutError",
        "RateLimitError",
        "AuthError",
        "RetriableError",
        "ProviderSkip",
        "SkipReason",
        "ConfigError",
        "AllFailedError",
        "ParallelExecutionError",
    ],
)
def test_errors_reexport(symbol: str) -> None:
    shadow_errors = _load_shadow_module()
    from adapter.core import errors as core_errors

    shadow_obj = getattr(shadow_errors, symbol)
    core_obj = getattr(core_errors, symbol)
    assert shadow_obj is core_obj


def test_errors_all_matches_core() -> None:
    shadow_errors = _load_shadow_module()
    from adapter.core import errors as core_errors

    assert shadow_errors.__all__ == core_errors.__all__
