from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from pathlib import Path
from typing import Any

from llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from llm_adapter.shadow_async import run_with_shadow_async
import pytest


class _DummyAsyncProvider:
    def __init__(
        self,
        name: str,
        behaviour: Callable[[ProviderRequest], Awaitable[ProviderResponse]],
    ) -> None:
        self._name = name
        self._behaviour = behaviour

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    async def invoke_async(self, request: ProviderRequest) -> ProviderResponse:
        return await self._behaviour(request)


async def _immediate_response(
    text: str,
    *,
    latency_ms: int,
    token_usage: TokenUsage,
) -> ProviderResponse:
    await asyncio.sleep(0)
    return ProviderResponse(text=text, latency_ms=latency_ms, token_usage=token_usage)


@pytest.mark.asyncio
async def test_run_with_shadow_async_success_records_metrics(tmp_path: Path) -> None:
    primary_usage = TokenUsage(prompt=2, completion=3)
    shadow_usage = TokenUsage(prompt=1, completion=4)

    primary = _DummyAsyncProvider(
        "primary",
        behaviour=lambda req: _immediate_response(
            "primary", latency_ms=50, token_usage=primary_usage
        ),
    )
    shadow = _DummyAsyncProvider(
        "shadow",
        behaviour=lambda req: _immediate_response(
            "shadow", latency_ms=70, token_usage=shadow_usage
        ),
    )

    request = ProviderRequest(prompt="hello", model="primary-model")
    metrics_path = tmp_path / "metrics.jsonl"

    response = await run_with_shadow_async(
        primary,
        shadow,
        request,
        metrics_path=metrics_path,
    )

    if isinstance(response, tuple):
        response, _metrics = response

    assert response.text == "primary"
    assert metrics_path.exists()

    records = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    record = records[0]

    assert record["event"] == "shadow_diff"
    assert record["primary_provider"] == "primary"
    assert record["shadow_provider"] == "shadow"
    assert record["shadow_outcome"] == "success"
    assert record["shadow_token_usage_total"] == shadow_usage.total
    assert record["shadow_text_len"] == len("shadow")
    assert record["shadow_error"] is None


@pytest.mark.asyncio
async def test_run_with_shadow_async_timeout_records_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_usage = TokenUsage(prompt=1, completion=1)

    primary = _DummyAsyncProvider(
        "primary",
        behaviour=lambda req: _immediate_response(
            "primary", latency_ms=40, token_usage=primary_usage
        ),
    )

    async def _never_returns(_: ProviderRequest) -> ProviderResponse:
        await asyncio.Future()
        raise AssertionError("unreachable")

    shadow = _DummyAsyncProvider("shadow", behaviour=_never_returns)

    async def _raise_timeout(
        awaitable: Awaitable[Any], timeout: float | None = None
    ) -> Any:
        raise TimeoutError

    monkeypatch.setattr("llm_adapter.shadow_async.asyncio.wait_for", _raise_timeout)

    request = ProviderRequest(prompt="hello", model="primary-model")
    metrics_path = tmp_path / "timeout.jsonl"

    response = await run_with_shadow_async(
        primary,
        shadow,
        request,
        metrics_path=metrics_path,
    )

    if isinstance(response, tuple):
        response, _metrics = response

    assert response.text == "primary"
    assert metrics_path.exists()

    record = json.loads(metrics_path.read_text())

    assert record["event"] == "shadow_diff"
    assert record["shadow_provider"] == "shadow"
    assert record["shadow_outcome"] == "timeout"
    assert record["shadow_error"] == "ShadowTimeout"
    assert record["shadow_duration_ms"] >= 0


@pytest.mark.asyncio
async def test_run_with_shadow_async_records_shadow_error(tmp_path: Path) -> None:
    primary = _DummyAsyncProvider(
        "primary",
        behaviour=lambda req: _immediate_response(
            "primary", latency_ms=25, token_usage=TokenUsage(prompt=1, completion=2)
        ),
    )

    async def _raise_error(_: ProviderRequest) -> ProviderResponse:
        raise RuntimeError("boom")

    shadow = _DummyAsyncProvider("shadow", behaviour=_raise_error)

    request = ProviderRequest(prompt="hello", model="primary-model")
    metrics_path = tmp_path / "error.jsonl"

    response = await run_with_shadow_async(
        primary,
        shadow,
        request,
        metrics_path=metrics_path,
    )

    if isinstance(response, tuple):
        response, _metrics = response

    assert response.text == "primary"
    assert metrics_path.exists()

    record = json.loads(metrics_path.read_text())

    assert record["shadow_outcome"] == "error"
    assert record["shadow_error"] == "RuntimeError"
    assert record["shadow_error_message"] == "boom"
