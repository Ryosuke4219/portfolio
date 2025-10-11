from __future__ import annotations

import threading
import time

import pytest

from adapter.core import _parallel_shim


def test_run_parallel_all_sync_limits_concurrency_and_completes_queue() -> None:
    start_gate = threading.Event()
    active_lock = threading.Lock()
    active_count = 0
    max_active = 0
    ready_events: list[threading.Event] = []

    def make_worker(index: int):
        ready = threading.Event()
        ready_events.append(ready)

        def worker() -> int:
            nonlocal active_count, max_active
            ready.set()
            start_gate.wait()
            with active_lock:
                active_count += 1
                max_active = max(max_active, active_count)
            time.sleep(0.01)
            with active_lock:
                active_count -= 1
            return index

        return worker

    workers = [make_worker(i) for i in range(4)]
    results: list[int] = []

    runner = threading.Thread(
        target=lambda: results.extend(
            _parallel_shim.run_parallel_all_sync(workers, max_concurrency=2)
        )
    )
    runner.start()

    assert ready_events[0].wait(0.5)
    assert ready_events[1].wait(0.5)
    assert not ready_events[2].wait(0.05)

    start_gate.set()
    runner.join(timeout=1.0)
    assert not runner.is_alive()

    assert results == [0, 1, 2, 3]
    assert max_active == 2


def test_run_parallel_all_sync_propagates_worker_exception() -> None:
    def boom() -> None:
        raise RuntimeError("explode")

    with pytest.raises(RuntimeError, match="explode"):
        _parallel_shim.run_parallel_all_sync([boom, boom], max_concurrency=2)


def test_run_parallel_any_sync_raises_parallel_execution_error_with_failures() -> None:
    def worker(name: str):
        def _run() -> None:
            raise RuntimeError(name)

        return _run

    with pytest.raises(_parallel_shim.ParallelExecutionError) as exc_info:
        _parallel_shim.run_parallel_any_sync(
            [worker("first"), worker("second")], max_concurrency=1
        )

    error = exc_info.value
    assert isinstance(error.__cause__, RuntimeError)
    assert error.failures is not None
    assert [str(exc) for exc in error.failures] == ["first", "second"]

