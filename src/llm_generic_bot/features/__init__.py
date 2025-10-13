"""機能モジュール群。"""

from .weather import (
    build_weather_post,
    WEATHER_CHANNEL_KEY,
    WEATHER_COOLDOWN_SECONDS_KEY,
    WEATHER_ENGAGEMENT_BASELINE_KEY,
    WEATHER_FEATURE_CONFIG_KEY,
    WEATHER_PERMIT_KEY,
    WeatherObservation,
    WeatherPost,
)

__all__ = [
    "WEATHER_CHANNEL_KEY",
    "WEATHER_COOLDOWN_SECONDS_KEY",
    "WEATHER_ENGAGEMENT_BASELINE_KEY",
    "WEATHER_FEATURE_CONFIG_KEY",
    "WEATHER_PERMIT_KEY",
    "WeatherObservation",
    "WeatherPost",
    "build_weather_post",
]
