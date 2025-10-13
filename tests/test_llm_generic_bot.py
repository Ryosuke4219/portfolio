from collections.abc import Mapping
from datetime import datetime, timedelta
import logging
from typing import Any

import pytest

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision
from llm_generic_bot.features.weather import (
    build_weather_post,
    WEATHER_ENGAGEMENT_BASELINE_KEY,
    WEATHER_FEATURE_CONFIG_KEY,
    WEATHER_PERMIT_KEY,
    WeatherObservation,
)


class DummyMetricsRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, dict[str, str]]] = []

    def increment(self, metric: str, amount: float = 1.0, *, tags: Mapping[str, str] | None = None) -> None:
        self.calls.append((metric, amount, dict(tags or {})))


class DummySender:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class AdvancingClock:
    def __init__(self, start: datetime, step: timedelta) -> None:
        self._current = start
        self._step = step

    def __call__(self) -> datetime:
        current = self._current
        self._current = current + self._step
        return current


@pytest.fixture
def weather_observation() -> WeatherObservation:
    return WeatherObservation(
        location="Tokyo",
        summary="晴れ時々くもり",
        temperature_c=26.5,
        precipitation_probability=0.15,
        engagement_hint=0.6,
    )


def test_build_weather_post_includes_engagement(weather_observation: WeatherObservation) -> None:
    config = {
        WEATHER_PERMIT_KEY: True,
        WEATHER_ENGAGEMENT_BASELINE_KEY: 0.4,
    }

    post = build_weather_post(weather_observation, config=config)

    assert post.payload["channel"] == "weather-updates"
    assert "Tokyo" in post.payload["text"]
    assert post.engagement["baseline"] == pytest.approx(0.4)
    assert post.engagement["score"] == pytest.approx(0.5)


def test_orchestrator_suppresses_when_permit_denied(
    weather_observation: WeatherObservation, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    sender = DummySender()
    metrics = DummyMetricsRecorder()

    def deny(_: dict[str, float]) -> PermitDecision:
        return PermitDecision(allowed=False, reason="quota")

    orchestrator = Orchestrator(
        sender=sender,
        permitter=deny,
        cooldown=timedelta(minutes=5),
        metrics_recorder=metrics,
        logger=logging.getLogger("llm_generic_bot.test"),
    )

    post = build_weather_post(weather_observation, config={WEATHER_PERMIT_KEY: True})
    permitted = orchestrator.dispatch(post)

    assert not permitted
    assert sender.payloads == []
    assert len(metrics.calls) == 1
    metric, amount, tags = metrics.calls[0]
    assert metric == "send.suppressed"
    assert amount == 1.0
    assert tags["suppression.reason"] == "permit"
    assert float(tags["engagement.baseline"]) == pytest.approx(post.engagement["baseline"])
    assert float(tags["engagement.score"]) == pytest.approx(post.engagement["score"])
    assert any(
        record.message == "send_suppressed" and getattr(record, "engagement", None) == post.engagement
        for record in caplog.records
    )


def test_orchestrator_enforces_cooldown(
    weather_observation: WeatherObservation, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    sender = DummySender()
    metrics = DummyMetricsRecorder()

    def allow(_: dict[str, float]) -> PermitDecision:
        return PermitDecision(allowed=True, reason=None)

    clock = AdvancingClock(datetime(2024, 1, 1, 0, 0, 0), timedelta(minutes=2))
    orchestrator = Orchestrator(
        sender=sender,
        permitter=allow,
        cooldown=timedelta(minutes=5),
        metrics_recorder=metrics,
        logger=logging.getLogger("llm_generic_bot.test"),
        clock=clock,
    )

    post = build_weather_post(
        weather_observation,
        config={
            WEATHER_FEATURE_CONFIG_KEY: True,
        },
    )

    first = orchestrator.dispatch(post)
    second = orchestrator.dispatch(post)

    assert first is True
    assert second is False
    assert len(sender.payloads) == 1

    suppressed_call = metrics.calls[-1]
    assert suppressed_call[0] == "send.suppressed"
    assert suppressed_call[2]["suppression.reason"] == "cooldown"
    assert any(
        record.message == "send_success" and getattr(record, "engagement", None) == post.engagement
        for record in caplog.records
    )
