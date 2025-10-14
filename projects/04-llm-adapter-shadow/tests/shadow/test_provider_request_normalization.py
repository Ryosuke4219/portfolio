from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy
from llm_adapter import provider_spi as provider_spi_module
from llm_adapter.provider_spi import ProviderRequest

hypothesis = pytest.importorskip("hypothesis")

st = hypothesis.strategies
given = hypothesis.given


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
