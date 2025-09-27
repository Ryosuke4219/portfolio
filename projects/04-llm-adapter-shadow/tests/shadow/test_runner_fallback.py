from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from src.llm_adapter import provider_spi as provider_spi_module
from src.llm_adapter.errors import ProviderSkip, RateLimitError, RetriableError, TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner import Runner


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class _ErrorProvider(ProviderSPI):
    def __init__(self, name: str, exc: Exception) -> None:
        self._name = name
        self._exc = exc

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        raise self._exc


class _SuccessProvider(ProviderSPI):
    def __init__(
        self,
        name: str,
        *,
        tokens_in: int = 12,
        tokens_out: int = 8,
        latency_ms: int = 5,
        cost_usd: float = 0.123,
    ) -> None:
        self._name = name
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._latency = latency_ms
        self._cost = cost_usd
        self.cost_calls: list[tuple[int, int]] = []

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            text=f"{self._name}:ok",
            latency_ms=self._latency,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            model=request.model,
        )

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        self.cost_calls.append((tokens_in, tokens_out))
        return self._cost


class _SkipProvider(ProviderSPI):
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderSkip(f"{self._name} unavailable")


def _run_and_collect(
    providers: Iterable[ProviderSPI],
    *,
    metrics_path: Path,
    prompt: str = "hello",
    expect_exception: type[Exception] | None = None,
) -> tuple[ProviderResponse | None, list[dict[str, Any]]]:
    runner = Runner(list(providers))
    request = ProviderRequest(prompt=prompt, model="demo-model")
    if expect_exception is None:
        response = runner.run(request, shadow_metrics_path=metrics_path)
        return response, _read_metrics(metrics_path)

    with pytest.raises(expect_exception):
        runner.run(request, shadow_metrics_path=metrics_path)
    return None, _read_metrics(metrics_path)


@pytest.mark.parametrize(
    (
        "providers",
        "expected_statuses",
        "expected_run_status",
        "expected_provider",
        "expected_attempts",
        "expected_skip_events",
        "expect_exception",
    ),
    [
        pytest.param(
            [_SuccessProvider("primary")],
            ["ok"],
            "ok",
            "primary",
            1,
            0,
            None,
            id="first-success",
        ),
        pytest.param(
            [_ErrorProvider("fail-first", RetriableError("transient")), _SuccessProvider("fallback")],
            ["error", "ok"],
            "ok",
            "fallback",
            2,
            0,
            None,
            id="fallback-success",
        ),
        pytest.param(
            [_ErrorProvider("slow", TimeoutError("too slow")), _ErrorProvider("slower", TimeoutError("still slow"))],
            ["error", "error"],
            "error",
            None,
            2,
            0,
            TimeoutError,
            id="all-fail",
        ),
        pytest.param(
            [_SkipProvider("skipped"), _SuccessProvider("active")],
            ["error", "ok"],
            "ok",
            "active",
            2,
            1,
            None,
            id="skip-then-success",
        ),
    ],
)
def test_runner_fallback_paths(
    tmp_path: Path,
    providers: list[ProviderSPI],
    expected_statuses: list[str],
    expected_run_status: str,
    expected_provider: str | None,
    expected_attempts: int,
    expected_skip_events: int,
    expect_exception: type[Exception] | None,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    response, records = _run_and_collect(
        providers,
        metrics_path=metrics_path,
        expect_exception=expect_exception,
    )

    provider_events = [rec for rec in records if rec["event"] == "provider_call"]
    assert len(provider_events) == len(expected_statuses)
    assert [event["status"] for event in provider_events] == expected_statuses

    run_event = next(rec for rec in records if rec["event"] == "run_metric")
    assert run_event["status"] == expected_run_status
    assert run_event.get("provider") == expected_provider
    assert run_event["attempts"] == expected_attempts

    skip_events = [rec for rec in records if rec["event"] == "provider_skipped"]
    assert len(skip_events) == expected_skip_events

    if expected_run_status == "ok":
        assert response is not None
    else:
        assert response is None


def test_rate_limit_triggers_backoff_and_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    rate_limited = _ErrorProvider("rate-limit", RateLimitError("slow down"))
    succeeding = _SuccessProvider("success")

    sleep_calls: list[float] = []

    def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.llm_adapter.runner.time.sleep", _fake_sleep)

    _, records = _run_and_collect([rate_limited, succeeding], metrics_path=metrics_path)

    assert sleep_calls == [0.05]
    first_call = next(
        rec
        for rec in records
        if rec["event"] == "provider_call" and rec["provider"] == "rate-limit"
    )
    assert first_call["status"] == "error"
    assert first_call["error_type"] == "RateLimitError"


def test_timeout_switches_to_next_provider(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    timeouting = _ErrorProvider("slow", TimeoutError("too slow"))
    succeeding = _SuccessProvider("success")

    _, records = _run_and_collect([timeouting, succeeding], metrics_path=metrics_path)

    timeout_event = next(
        rec
        for rec in records
        if rec["event"] == "provider_call" and rec["provider"] == "slow"
    )
    assert timeout_event["status"] == "error"
    assert timeout_event["error_type"] == "TimeoutError"

    success_event = next(
        rec
        for rec in records
        if rec["event"] == "provider_call" and rec["provider"] == "success"
    )
    assert success_event["status"] == "ok"


def test_run_metric_contains_tokens_and_cost(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    succeeding = _SuccessProvider("success", tokens_in=21, tokens_out=9, cost_usd=0.456)

    _, records = _run_and_collect([succeeding], metrics_path=metrics_path)

    run_event = next(rec for rec in records if rec["event"] == "run_metric")
    assert run_event["tokens_in"] == 21
    assert run_event["tokens_out"] == 9
    assert run_event["cost_usd"] == pytest.approx(0.456)
    assert succeeding.cost_calls == [(21, 9)]


def _message_entries() -> SearchStrategy[Mapping[str, Any]]:
    text_strategy = st.text()
    sequence_strategy = st.lists(text_strategy, max_size=3).map(tuple)
    content_strategy = st.one_of(
        st.none(),
        text_strategy,
        sequence_strategy,
        st.integers(),
    )
    role_strategy = st.one_of(st.none(), text_strategy)
    extra_strategy = st.dictionaries(
        st.text(min_size=1),
        st.one_of(text_strategy, st.integers()),
        max_size=1,
    )
    return st.builds(
        lambda role, content, extra: {"role": role, "content": content, **extra},
        role_strategy,
        content_strategy,
        extra_strategy,
    )


@given(
    prompt=st.one_of(st.none(), st.text()),
    messages=st.lists(_message_entries(), max_size=4),
)
def test_provider_request_normalization_boundaries(
    prompt: str | None, messages: Sequence[Mapping[str, Any]]
) -> None:
    prompt_value = "" if prompt is None else prompt
    request = ProviderRequest(prompt=prompt_value, messages=messages, model="demo-model")

    expected_prompt = prompt_value.strip()
    normalized_messages: list[Mapping[str, Any]] = []
    for entry in messages:
        if isinstance(entry, Mapping):
            normalized = provider_spi_module._normalize_message(entry)
            if normalized:
                normalized_messages.append(normalized)

    if not normalized_messages and expected_prompt:
        normalized_messages.append({"role": "user", "content": expected_prompt})

    if not expected_prompt and normalized_messages:
        expected_prompt = provider_spi_module._extract_prompt_from_messages(normalized_messages)

    assert request.chat_messages == normalized_messages
    assert request.prompt_text == expected_prompt

    for message in request.chat_messages:
        role = message["role"]
        assert isinstance(role, str)
        assert role.strip() == role
        assert role

        content = message["content"]
        if isinstance(content, str):
            assert content.strip() == content
            assert content
        elif isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray, str)):
            assert content
            for part in content:
                assert isinstance(part, str)
                assert part.strip() == part
                assert part
        else:
            assert content is not None
