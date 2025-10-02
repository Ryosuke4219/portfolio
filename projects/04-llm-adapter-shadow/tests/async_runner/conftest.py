from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from _pytest.recwarn import WarningsRecorder
import pytest

from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage


class _FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, duration: float) -> None:
        self.current += duration

    async def async_sleep(self, duration: float) -> None:
        self.current += duration


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.events if kind == event_type]


class _AsyncProbeProvider:
    def __init__(
        self,
        name: str,
        *,
        delay: float,
        text: str | None = None,
        failures: list[BaseException] | None = None,
        block: bool = False,
    ) -> None:
        self._name = name
        self._delay = delay
        self._text = text or name
        self.cancelled = False
        self.finished = False
        self.invocations = 0
        self._failures = list(failures or [])
        self._block = block

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
        self.invocations += 1
        try:
            if self._failures:
                raise self._failures.pop(0)
            if self._block:
                await asyncio.Event().wait()
                latency_ms = 0
            elif self._delay <= 0:
                latency_ms = 0
            else:
                await asyncio.sleep(self._delay)
                latency_ms = int(self._delay * 1000)
            return ProviderResponse(
                text=f"{self._text}:{request.prompt}",
                latency_ms=latency_ms,
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished = True


class _StaticProvider:
    def __init__(self, name: str, text: str, latency_ms: int) -> None:
        self._name = name
        self._text = text
        self._latency_ms = latency_ms

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=self._text,
            latency_ms=self._latency_ms,
            token_usage=TokenUsage(prompt=1, completion=1),
            model=request.model,
            finish_reason="stop",
        )


T = TypeVar("T")


def _run_without_warnings(action: Callable[[], T]) -> T:
    try:
        warns_cm = pytest.warns(None)  # type: ignore[call-overload]
    except TypeError:
        warns_cm = WarningsRecorder(_ispytest=True)
    with warns_cm as warnings_record:
        result = action()
    assert len(warnings_record) == 0
    return result


def _patch_runner_sleep(
    monkeypatch: pytest.MonkeyPatch,
    clock: _FakeClock,
    calls: list[float] | None = None,
) -> None:
    async def _fake_sleep(duration: float) -> None:
        if calls is not None:
            calls.append(duration)
        await clock.async_sleep(duration)

    monkeypatch.setattr("src.llm_adapter.runner_async.asyncio.sleep", _fake_sleep)
    monkeypatch.setattr("src.llm_adapter.parallel_exec.asyncio.sleep", _fake_sleep)


__all__ = [
    "_AsyncProbeProvider",
    "_CapturingLogger",
    "_FakeClock",
    "_StaticProvider",
    "_patch_runner_sleep",
    "_run_without_warnings",
]
