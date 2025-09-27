from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy
from src.llm_adapter import provider_spi as provider_spi_module
from src.llm_adapter.errors import RateLimitError, RetriableError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner import AsyncRunner
from src.llm_adapter.runner_config import BackoffPolicy, RunnerConfig

from ._runner_test_helpers import FakeLogger, _ErrorProvider, _SuccessProvider


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
