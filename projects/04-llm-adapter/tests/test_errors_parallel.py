"""Tests for parallel execution specific errors."""
from adapter.core.errors import FatalError, ParallelExecutionError


def test_parallel_execution_error_inherits_and_preserves_attributes() -> None:
    failures = [RuntimeError("foo"), RuntimeError("bar")]
    batch = {"inputs": [1, 2]}

    error = ParallelExecutionError(
        "parallel execution failed",
        failures=failures,
        batch=batch,
    )

    assert isinstance(error, FatalError)
    assert error.failures is failures
    assert error.batch is batch
