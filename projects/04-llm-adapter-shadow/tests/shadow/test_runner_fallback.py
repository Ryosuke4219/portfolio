from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy
from src.llm_adapter import provider_spi as provider_spi_module
from src.llm_adapter.errors import AuthError, RateLimitError, RetriableError, TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderSPI
from src.llm_adapter.runner import AsyncRunner
from src.llm_adapter.runner_config import BackoffPolicy, RunnerConfig

from ._runner_test_helpers import (
    FakeLogger,
    _ErrorProvider,
    _SuccessProvider,
    _SkipProvider,
    _run_and_collect,
)


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
            [
                _ErrorProvider("fail-first", RetriableError("transient")),
                _SuccessProvider("fallback"),
            ],
            ["error", "ok"],
            "ok",
            "fallback",
            2,
            0,
            None,
            id="fallback-success",
        ),
        pytest.param(
            [
                _ErrorProvider("slow", TimeoutError("too slow")),
                _ErrorProvider("slower", TimeoutError("still slow")),
            ],
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
    providers: list[ProviderSPI],
    expected_statuses: list[str],
    expected_run_status: str,
    expected_provider: str | None,
    expected_attempts: int,
    expected_skip_events: int,
    expect_exception: type[Exception] | None,
) -> None:
    response, logger = _run_and_collect(
        providers,
        expect_exception=expect_exception,
    )

    provider_events = logger.of_type("provider_call")
    assert len(provider_events) == len(expected_statuses)
    assert [event["status"] for event in provider_events] == expected_statuses

    run_event = logger.of_type("run_metric")[0]
    assert run_event["status"] == expected_run_status
    assert run_event.get("provider") == expected_provider
    assert run_event["attempts"] == expected_attempts

    skip_events = logger.of_type("provider_skipped")
    assert len(skip_events) == expected_skip_events

    if expected_run_status == "ok":
        assert response is not None
    else:
        assert response is None


def test_rate_limit_triggers_backoff_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rate_limited = _ErrorProvider("rate-limit", RateLimitError("slow down"))
    succeeding = _SuccessProvider("success")

    sleep_calls: list[float] = []

    def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.llm_adapter.runner.time.sleep", _fake_sleep)

    _, logger = _run_and_collect(
        [rate_limited, succeeding],
        config=RunnerConfig(backoff=BackoffPolicy(rate_limit_sleep_s=0.123)),
    )

    assert sleep_calls == [0.123]
    first_call = next(
        record
        for record in logger.of_type("provider_call")
        if record["provider"] == "rate-limit"
    )
    assert first_call["status"] == "error"
    assert first_call["error_type"] == "RateLimitError"
    assert first_call["error_family"] == "rate_limit"


def test_timeout_switches_to_next_provider() -> None:
    timeouting = _ErrorProvider("slow", TimeoutError("too slow"))
    succeeding = _SuccessProvider("success")

    _, logger = _run_and_collect([timeouting, succeeding])

    timeout_event = next(
        record
        for record in logger.of_type("provider_call")
        if record["provider"] == "slow"
    )
    assert timeout_event["status"] == "error"
    assert timeout_event["error_type"] == "TimeoutError"
    assert timeout_event["error_family"] == "retryable"

    success_event = next(
        record
        for record in logger.of_type("provider_call")
        if record["provider"] == "success"
    )
    assert success_event["status"] == "ok"


def test_provider_skip_logs_error_family() -> None:
    response, logger = _run_and_collect([_SkipProvider("skipped"), _SuccessProvider("active")])

    assert response is not None
    skip_event = next(
        record for record in logger.of_type("provider_call") if record["provider"] == "skipped"
    )
    assert skip_event["status"] == "error"
    assert skip_event["error_type"] == "ProviderSkip"
    assert skip_event["error_family"] == "skip"


def test_fatal_error_logs_error_family() -> None:
    _, logger = _run_and_collect(
        [_ErrorProvider("fatal", AuthError("invalid"))],
        expect_exception=AuthError,
    )

    fatal_event = logger.of_type("provider_call")[0]
    assert fatal_event["status"] == "error"
    assert fatal_event["error_type"] == "AuthError"
    assert fatal_event["error_family"] == "fatal"


def test_provider_chain_failed_records_last_error_family() -> None:
    _, logger = _run_and_collect(
        [
            _ErrorProvider("first", TimeoutError("slow")),
            _ErrorProvider("second", RetriableError("oops")),
        ],
        expect_exception=RetriableError,
    )

    chain_event = logger.of_type("provider_chain_failed")[0]
    assert chain_event["last_error_type"] == "RetriableError"
    assert chain_event["last_error_family"] == "retryable"

    run_event = logger.of_type("run_metric")[0]
    assert run_event["status"] == "error"
    assert run_event["error_family"] == "retryable"


@pytest.mark.asyncio
async def test_async_rate_limit_triggers_backoff_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rate_limited = _ErrorProvider("rate-limit", RateLimitError("slow down"))
    succeeding = _SuccessProvider("success")

    sleep_calls: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.llm_adapter.runner.asyncio.sleep", _fake_sleep)

    logger = FakeLogger()
    runner = AsyncRunner(
        [rate_limited, succeeding],
        logger=logger,
        config=RunnerConfig(backoff=BackoffPolicy(rate_limit_sleep_s=0.321)),
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    response = await runner.run_async(request, shadow_metrics_path=None)

    assert response.text == "success:ok"
    assert sleep_calls == [0.321]
    first_call = next(
        record
        for record in logger.of_type("provider_call")
        if record["provider"] == "rate-limit"
    )
    assert first_call["status"] == "error"
    assert first_call["error_type"] == "RateLimitError"
    assert first_call["error_family"] == "rate_limit"


@pytest.mark.asyncio
async def test_async_retryable_error_logs_family() -> None:
    logger = FakeLogger()
    runner = AsyncRunner([_ErrorProvider("oops", RetriableError("nope"))], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises(RetriableError):
        await runner.run_async(request, shadow_metrics_path=None)

    provider_event = logger.of_type("provider_call")[0]
    assert provider_event["error_family"] == "retryable"

    chain_event = logger.of_type("provider_chain_failed")[0]
    assert chain_event["last_error_family"] == "retryable"

def test_run_metric_contains_tokens_and_cost() -> None:
    succeeding = _SuccessProvider("success", tokens_in=21, tokens_out=9, cost_usd=0.456)

    _, logger = _run_and_collect([succeeding])

    run_event = logger.of_type("run_metric")[0]
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
        elif isinstance(content, Sequence) and not isinstance(content, bytes | bytearray | str):
            assert content
            for part in content:
                assert isinstance(part, str)
                assert part.strip() == part
                assert part
        else:
            assert content is not None
