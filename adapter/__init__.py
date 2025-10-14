"""トップレベル `adapter` パッケージのシム。"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Protocol

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET_DIR = _REPO_ROOT / "projects" / "04-llm-adapter" / "adapter"
if not _TARGET_DIR.exists():  # pragma: no cover - 開発環境の構成不備
    raise ImportError("projects/04-llm-adapter/adapter が見つかりません")

_spec = spec_from_file_location(
    __name__,
    _TARGET_DIR / "__init__.py",
    submodule_search_locations=[str(_TARGET_DIR)],
)
if _spec is None or _spec.loader is None:  # pragma: no cover - importlib 異常
    raise ImportError("adapter モジュールのロードに失敗しました")

_module = module_from_spec(_spec)
sys.modules[__name__] = _module
_spec.loader.exec_module(_module)

globals().update({k: v for k, v in _module.__dict__.items() if k != "__dict__"})


def _ensure_src_on_path() -> None:
    src_root = (_REPO_ROOT / "src").resolve()
    src_str = str(src_root)
    if src_root.exists() and src_str not in sys.path:
        sys.path.insert(0, src_str)


def _install_structured_logging_module() -> None:
    module_name = "adapter.core.observability"
    if module_name in sys.modules:
        return

    class _EventLogger(Protocol):
        def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
            """Structured logger interface."""

    class StructuredLogger:
        """Emit structured engagement logs to the configured sink."""

        def __init__(self, sink: _EventLogger) -> None:
            self._sink = sink

        def send_success(
            self,
            *,
            provider: str,
            run_id: str,
            message_id: str,
            engagement_score: float,
            engagement_bucket: str,
            engagement_threshold: float,
            suppressed: bool = False,
            extra: Mapping[str, Any] | None = None,
        ) -> None:
            payload: dict[str, Any] = {
                "provider": provider,
                "run_id": run_id,
                "message_id": message_id,
                "engagement": {
                    "score": float(engagement_score),
                    "bucket": engagement_bucket,
                    "threshold": float(engagement_threshold),
                    "suppressed": bool(suppressed),
                },
            }
            if extra is not None:
                payload.update(dict(extra))
            self._sink.emit("send_success", payload)

    structured_logging = ModuleType("adapter.core.observability.structured_logging")
    structured_logging.StructuredLogger = StructuredLogger  # type: ignore[attr-defined]
    structured_logging.__all__ = ["StructuredLogger"]

    observability = ModuleType(module_name)
    observability.structured_logging = structured_logging  # type: ignore[attr-defined]
    observability.__all__ = ["structured_logging"]

    sys.modules["adapter.core.observability.structured_logging"] = structured_logging
    sys.modules[module_name] = observability

    core_module = sys.modules.get("adapter.core")
    if core_module is not None:
        core_module.observability = observability


def _install_weather_module() -> None:
    module_name = "adapter.core.providers.weather"
    if module_name in sys.modules:
        return

    class _MetricsRecorder(Protocol):
        def record(self, event: str, **fields: Any) -> None:
            """Metrics sink for engagement events."""

    class _EventLogger(Protocol):
        def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
            """Structured event logger."""

    class WeatherEngagementGate:
        """Minimum viable engagement gate for weather notifications."""

        def __init__(
            self,
            *,
            min_samples: int,
            unlock_threshold: float,
            metrics: _MetricsRecorder,
            logger: _EventLogger,
        ) -> None:
            if min_samples < 1:
                raise ValueError("min_samples must be at least 1")
            self._min_samples = int(min_samples)
            self._threshold = float(unlock_threshold)
            self._metrics = metrics
            self._logger = logger
            self._scores: list[float] = []
            self._channels: list[str] = []

        def track(self, *, score: float, channel: str) -> None:
            self._scores.append(float(score))
            self._channels.append(channel)

        def can_send(self) -> bool:
            if len(self._scores) < self._min_samples:
                return False
            return self._scores[-1] >= self._threshold

        def publish_success(self, *, run_id: str, message_id: str) -> None:
            score = self._scores[-1] if self._scores else 0.0
            suppressed = not self.can_send()
            self._metrics.record(
                "weather_send_success",
                run_id=run_id,
                message_id=message_id,
                engagement_score=score,
                engagement_threshold=self._threshold,
                suppressed=suppressed,
            )
            engagement = {
                "score": score,
                "threshold": self._threshold,
                "suppressed": suppressed,
                "bucket": "high" if score >= self._threshold else "low",
            }
            record = {
                "provider": "weather",
                "run_id": run_id,
                "message_id": message_id,
                "engagement": engagement,
            }
            self._logger.emit("send_success", record)

    engagement = ModuleType("adapter.core.providers.weather.engagement")
    engagement.WeatherEngagementGate = WeatherEngagementGate  # type: ignore[attr-defined]
    engagement.__all__ = ["WeatherEngagementGate"]

    weather = ModuleType(module_name)
    weather.engagement = engagement  # type: ignore[attr-defined]
    weather.__all__ = ["engagement"]

    sys.modules["adapter.core.providers.weather.engagement"] = engagement
    sys.modules[module_name] = weather

    providers_module = sys.modules.get("adapter.core.providers")
    if providers_module is not None:
        providers_module.weather = weather


def _install_compat_shims() -> None:
    _ensure_src_on_path()
    _install_structured_logging_module()
    _install_weather_module()


_install_compat_shims()
