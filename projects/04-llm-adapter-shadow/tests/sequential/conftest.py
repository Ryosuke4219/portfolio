from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from llm_adapter.observability import EventLogger
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from llm_adapter.runner_sync import Runner
from llm_adapter.runner_sync_modes import SyncRunContext


class _FailingProvider:
    def __init__(self, name: str, error: Exception) -> None:
        self._name = name
        self._error = error
        self.calls = 0

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        raise self._error


class _SuccessfulProvider:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - patched
        raise AssertionError("_invoke_provider_sync is patched in tests")


class _RecordingLogger(EventLogger):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))


def _make_context(runner: Runner, *, logger: EventLogger | None = None) -> SyncRunContext:
    return SyncRunContext(
        runner=runner,
        request=ProviderRequest(model="gpt-test", prompt="hello"),
        event_logger=logger,
        metadata={},
        run_started=time.time(),
        request_fingerprint="fp",
        shadow=None,
        shadow_used=False,
        metrics_path=None,
        run_parallel_all=lambda workers, **_: [],
        run_parallel_any=lambda workers, **_: workers[0](),
    )


__all__ = [
    "_FailingProvider",
    "_SuccessfulProvider",
    "_RecordingLogger",
    "_make_context",
]
