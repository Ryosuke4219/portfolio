from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
import json
from pathlib import Path
import time
from typing import Any

import pytest

from llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from llm_adapter.providers.mock import MockProvider

__all__ = [
    "RecordingLogger",
    "_StaticProvider",
    "_RetryProbeProvider",
    "_RecordingThreadPoolExecutor",
    "_install_recording_executor",
    "_read_metrics",
    "_worker_for",
]


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.events if kind == event_type]


class _StaticProvider:
    def __init__(self, name: str, text: str, latency_ms: int) -> None:
        self._name = name
        self._text = text
        self.latency_ms = latency_ms

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._text,
            latency_ms=self.latency_ms,
            token_usage=TokenUsage(prompt=1, completion=1),
            model=request.model,
            finish_reason="stop",
        )


class _RetryProbeProvider:
    def __init__(
        self,
        name: str,
        outcomes: Sequence[object],
        *,
        latency_s: float = 0.0,
    ) -> None:
        if not outcomes:
            raise ValueError("outcomes must not be empty")
        self._name = name
        self._outcomes = list(outcomes)
        self._latency_s = latency_s
        self.call_count = 0
        self.outcome_log: list[str] = []

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.call_count += 1
        if self._latency_s > 0:
            time.sleep(self._latency_s)
        index = self.call_count - 1
        outcome = (
            self._outcomes[index] if index < len(self._outcomes) else self._outcomes[-1]
        )
        if isinstance(outcome, Exception):
            self.outcome_log.append(type(outcome).__name__)
            raise outcome
        self.outcome_log.append("ok")
        if isinstance(outcome, ProviderResponse):
            return outcome
        text = str(outcome)
        return ProviderResponse(
            text=f"{self._name}:attempt{self.call_count}:{text}",
            latency_ms=int(self._latency_s * 1000),
            token_usage=TokenUsage(prompt=1, completion=1),
            model=request.model,
            finish_reason="stop",
            raw={"attempt": self.call_count, "payload": text},
        )


class _RecordingThreadPoolExecutor(ThreadPoolExecutor):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.submitted: list[Future[Any]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        future = super().submit(fn, *args, **kwargs)
        self.submitted.append(future)
        return future


def _install_recording_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> list[_RecordingThreadPoolExecutor]:
    created: list[_RecordingThreadPoolExecutor] = []

    class _Factory(_RecordingThreadPoolExecutor):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(
        "llm_adapter.parallel_exec.ThreadPoolExecutor",
        _Factory,
    )
    return created


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _worker_for(
    provider: MockProvider, request: ProviderRequest
) -> Callable[[], ProviderResponse]:
    def _invoke() -> ProviderResponse:
        return provider.invoke(request)

    return _invoke
