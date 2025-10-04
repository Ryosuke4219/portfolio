"""Logger resolution and request hashing helpers."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ...observability import EventLogger, JsonlLogger
from ...utils import content_hash

if TYPE_CHECKING:
    from ...provider_spi import AsyncProviderSPI, ProviderRequest, ProviderSPI

MetricsPath = str | Path | None


def resolve_event_logger(
    logger: EventLogger | None,
    metrics_path: MetricsPath,
) -> tuple[EventLogger | None, str | None]:
    """Resolve the event logger and materialized metrics path."""
    metrics_path_str = None if metrics_path is None else str(Path(metrics_path))
    if metrics_path_str is None:
        return None, None
    if logger is not None:
        return logger, metrics_path_str
    return JsonlLogger(metrics_path_str), metrics_path_str


def _provider_name(provider: ProviderSPI | AsyncProviderSPI | None) -> str | None:
    if provider is None:
        return None
    if hasattr(provider, "name"):
        name = provider.name  # type: ignore[attr-defined]
        if callable(name):
            return str(name())
    return None


def _request_hash(provider_name: str | None, request: ProviderRequest) -> str | None:
    if provider_name is None:
        return None
    return content_hash(
        provider_name,
        request.prompt_text,
        request.options,
        request.max_tokens,
    )


__all__ = [
    "MetricsPath",
    "resolve_event_logger",
    "_provider_name",
    "_request_hash",
]
