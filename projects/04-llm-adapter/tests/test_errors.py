"""Tests for adapter.core.errors module."""
from __future__ import annotations

import importlib


def test_parallel_execution_error_exports_and_attrs() -> None:
    module = importlib.import_module("adapter.core.errors")

    assert hasattr(module, "ParallelExecutionError")

    error = module.ParallelExecutionError(
        "parallel execution failed",
        failures=[{"id": 1, "error": "timeout"}],
        batch={"job": "test"},
    )

    assert error.failures == [{"id": 1, "error": "timeout"}]
    assert error.batch == {"job": "test"}
    assert str(error) == "parallel execution failed"
