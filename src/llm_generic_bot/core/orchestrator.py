"""投稿オーケストレーター。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Protocol

from ..features.weather import WeatherPost

Logger = logging.Logger


class MetricsRecorder(Protocol):
    """メトリクス送出インターフェース。"""

    def increment(self, metric: str, amount: float = 1.0, *, tags: Mapping[str, str] | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class PermitDecision:
    """送信許可判定。"""

    allowed: bool
    reason: str | None = None


class Orchestrator:
    """送信判定とメトリクス連携を司る。"""

    def __init__(
        self,
        *,
        sender: Callable[[dict[str, Any]], None],
        permitter: Callable[[dict[str, float]], PermitDecision],
        cooldown: timedelta,
        metrics_recorder: MetricsRecorder,
        logger: Logger,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sender = sender
        self._permitter = permitter
        self._cooldown = cooldown
        self._metrics = metrics_recorder
        self._logger = logger
        self._clock = clock or datetime.utcnow
        self._last_sent_at: datetime | None = None

    def dispatch(self, post: WeatherPost) -> bool:
        """投稿送信を試行し、送信した場合は ``True`` を返す。"""

        decision = self._permitter(post.engagement)
        if not decision.allowed:
            self._record_suppressed(post, reason="permit", details=decision.reason)
            return False

        now = self._clock()
        if self._is_cooldown_active(now):
            self._record_suppressed(post, reason="cooldown", details="active")
            return False

        self._sender(post.payload)
        self._last_sent_at = now
        self._record_success(post)
        return True

    def _is_cooldown_active(self, now: datetime) -> bool:
        if self._last_sent_at is None:
            return False
        return now - self._last_sent_at < self._cooldown

    def _record_success(self, post: WeatherPost) -> None:
        tags = self._build_engagement_tags(post.engagement)
        self._metrics.increment("send.success", tags=tags)
        self._logger.info(
            "send_success",
            extra={
                "event": "send_success",
                "engagement": post.engagement,
            },
        )

    def _record_suppressed(self, post: WeatherPost, *, reason: str, details: str | None) -> None:
        tags = self._build_engagement_tags(post.engagement)
        tags["suppression.reason"] = reason
        self._metrics.increment("send.suppressed", tags=tags)
        self._logger.info(
            "send_suppressed",
            extra={
                "event": "send_suppressed",
                "reason": details or reason,
                "engagement": post.engagement,
            },
        )

    @staticmethod
    def _build_engagement_tags(engagement: Mapping[str, float]) -> dict[str, str]:
        return {f"engagement.{key}": f"{value:.6f}" for key, value in engagement.items()}
