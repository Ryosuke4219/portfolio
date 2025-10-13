"""天気投稿の生成ロジック。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

WEATHER_FEATURE_CONFIG_KEY = "llm_generic_bot.weather"
WEATHER_CHANNEL_KEY = f"{WEATHER_FEATURE_CONFIG_KEY}.channel"
WEATHER_PERMIT_KEY = f"{WEATHER_FEATURE_CONFIG_KEY}.permit"
WEATHER_COOLDOWN_SECONDS_KEY = f"{WEATHER_FEATURE_CONFIG_KEY}.cooldown_seconds"
WEATHER_ENGAGEMENT_BASELINE_KEY = f"{WEATHER_FEATURE_CONFIG_KEY}.engagement_baseline"
WEATHER_COPY_TEMPLATE_KEY = f"{WEATHER_FEATURE_CONFIG_KEY}.template"

_DEFAULT_CHANNEL = "weather-updates"
_DEFAULT_TEMPLATE = "{location}: {summary} {temperature_c:.1f}°C"


@dataclass(frozen=True, slots=True)
class WeatherObservation:
    """単一地点の天気情報。"""

    location: str
    summary: str
    temperature_c: float
    precipitation_probability: float | None = None
    engagement_hint: float | None = None


@dataclass(frozen=True, slots=True)
class WeatherPost:
    """送信ペイロードとエンゲージメント指標。"""

    payload: dict[str, Any]
    engagement: dict[str, float]


def _format_text(observation: WeatherObservation, template: str) -> str:
    base_text = template.format(
        location=observation.location,
        summary=observation.summary,
        temperature_c=observation.temperature_c,
    )
    if observation.precipitation_probability is None:
        return base_text
    probability = max(0.0, min(observation.precipitation_probability, 1.0))
    return f"{base_text} (降水確率 {probability * 100:.0f}%)"


def _calculate_engagement(
    observation: WeatherObservation, baseline: float
) -> dict[str, float]:
    hint = observation.engagement_hint
    if hint is None:
        score = baseline
    else:
        score = (baseline + hint) / 2
    return {
        "baseline": baseline,
        "score": score,
    }


def build_weather_post(
    observation: WeatherObservation, *, config: Mapping[str, Any]
) -> WeatherPost:
    """天気投稿のペイロードを生成する。"""

    channel = str(config.get(WEATHER_CHANNEL_KEY, _DEFAULT_CHANNEL))
    template = str(config.get(WEATHER_COPY_TEMPLATE_KEY, _DEFAULT_TEMPLATE))
    baseline_value = float(config.get(WEATHER_ENGAGEMENT_BASELINE_KEY, 0.0))

    payload = {
        "channel": channel,
        "text": _format_text(observation, template),
        "location": observation.location,
        "summary": observation.summary,
    }
    engagement = _calculate_engagement(observation, baseline_value)
    return WeatherPost(payload=payload, engagement=engagement)
