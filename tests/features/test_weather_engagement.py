"""Weather チャネル向けエンゲージメント制御の失敗テスト。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from adapter.core.providers.weather import engagement as weather_engagement


@dataclass
class DummyMetricsRecorder:
    events: list[tuple[str, dict[str, Any]]]

    def record(self, event: str, **fields: Any) -> None:
        self.events.append((event, dict(fields)))


class DummyStructuredLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, record: dict[str, Any]) -> None:
        self.events.append((event, dict(record)))


@pytest.fixture()
def dummy_metrics() -> DummyMetricsRecorder:
    return DummyMetricsRecorder(events=[])


@pytest.fixture()
def dummy_logger() -> DummyStructuredLogger:
    return DummyStructuredLogger()


def test_weather_low_engagement_is_suppressed(
    dummy_metrics: DummyMetricsRecorder, dummy_logger: DummyStructuredLogger
) -> None:
    gate = weather_engagement.WeatherEngagementGate(
        min_samples=3,
        unlock_threshold=0.6,
        metrics=dummy_metrics,
        logger=dummy_logger,
    )

    gate.track(score=0.05, channel="push")
    gate.track(score=0.10, channel="push")

    assert gate.can_send() is False


def test_weather_unlocks_after_threshold(
    dummy_metrics: DummyMetricsRecorder, dummy_logger: DummyStructuredLogger
) -> None:
    gate = weather_engagement.WeatherEngagementGate(
        min_samples=3,
        unlock_threshold=0.6,
        metrics=dummy_metrics,
        logger=dummy_logger,
    )

    gate.track(score=0.05, channel="push")
    gate.track(score=0.10, channel="push")
    gate.track(score=0.85, channel="push")

    assert gate.can_send() is True


def test_weather_metrics_and_logs_include_engagement(
    dummy_metrics: DummyMetricsRecorder, dummy_logger: DummyStructuredLogger
) -> None:
    gate = weather_engagement.WeatherEngagementGate(
        min_samples=2,
        unlock_threshold=0.5,
        metrics=dummy_metrics,
        logger=dummy_logger,
    )

    gate.track(score=0.7, channel="push")
    gate.track(score=0.8, channel="push")
    assert gate.can_send() is True

    gate.publish_success(run_id="run-1", message_id="msg-123")

    event, payload = dummy_metrics.events[-1]
    assert event == "weather_send_success"
    assert payload["engagement_score"] == pytest.approx(0.8)
    assert payload["suppressed"] is False

    log_event, log_payload = dummy_logger.events[-1]
    assert log_event == "send_success"
    assert log_payload["engagement"]["score"] == pytest.approx(0.8)
    assert log_payload["engagement"]["threshold"] == pytest.approx(0.5)
    assert log_payload["engagement"]["suppressed"] is False
