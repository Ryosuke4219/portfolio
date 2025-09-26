import json
import threading
from pathlib import Path

import pytest

from src.llm_adapter.metrics import log_event


@pytest.mark.parametrize("thread_count,event_per_thread", [(8, 200)])
def test_log_event_threadsafe(tmp_path: Path, thread_count: int, event_per_thread: int) -> None:
    target = tmp_path / "events.jsonl"
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
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == expected_records

    for line in lines:
        record = json.loads(line)
        assert record["event"] == "test"
        assert "thread" in record
        assert "index" in record
