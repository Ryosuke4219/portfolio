"""Structured logging の追加メタデータ検証の失敗テスト。"""

from __future__ import annotations

from typing import Any

import pytest

from adapter.core.observability import structured_logging


class DummySink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, record: dict[str, Any]) -> None:
        self.events.append((event, dict(record)))


def test_send_success_log_contains_engagement_metadata() -> None:
    sink = DummySink()
    logger = structured_logging.StructuredLogger(sink)

    logger.send_success(
        provider="weather",
        run_id="run-1",
        message_id="msg-123",
        engagement_score=0.64,
        engagement_bucket="medium",
        engagement_threshold=0.6,
    )

    event, record = sink.events[-1]
    assert event == "send_success"
    assert record["engagement"]["score"] == pytest.approx(0.64)
    assert record["engagement"]["bucket"] == "medium"
    assert record["engagement"]["threshold"] == pytest.approx(0.6)
