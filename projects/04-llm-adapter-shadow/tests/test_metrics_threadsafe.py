import threading

import pytest

from src.llm_adapter.metrics import log_event
from tests.helpers.fakes import FakeLogger


@pytest.mark.parametrize("thread_count,event_per_thread", [(8, 200)])
def test_log_event_threadsafe(
    monkeypatch: pytest.MonkeyPatch, thread_count: int, event_per_thread: int
) -> None:
    logger = FakeLogger()
    monkeypatch.setattr("src.llm_adapter.metrics._DEFAULT_LOGGER", logger)
    target = "memory://events"
    start_barrier = threading.Barrier(thread_count)

    def worker(thread_id: int) -> None:
        start_barrier.wait()
        for i in range(event_per_thread):
            log_event(
                "test",
                target,
                thread=thread_id,
                index=i,
            )

    threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected_records = thread_count * event_per_thread
    assert len(logger.events) == expected_records

    for _, path, record in logger.events:
        assert path == target
        assert record["event"] == "test"
        assert "thread" in record
        assert "index" in record
