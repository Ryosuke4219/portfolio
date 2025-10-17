from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies
given = hypothesis.given

from adapter.core.errors import RateLimitError
from adapter.core.models import PricingConfig, ProviderConfig, QualityGatesConfig, RateLimitConfig, RetryConfig
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import openai as openai_module
from adapter.core.providers.openai_utils import extract_text_from_response, extract_usage_tokens


def _make_config(raw: dict[str, Any] | None = None) -> ProviderConfig:
    return ProviderConfig(Path("config.yml"), None, "openai", None, "gpt-4o", "OPENAI_KEY", 0, 0.0, 1.0, 0, 30, RetryConfig(), False, PricingConfig(), RateLimitConfig(), QualityGatesConfig(), raw or {})


def test_openai_provider_responses_mode_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_KEY", "sk-test")
    captured: dict[str, Any] = {}
    result = SimpleNamespace(output_text="generated", usage={"prompt_tokens": 11, "completion_tokens": 5}, model_dump=lambda: {"output_text": "generated", "usage": {"prompt_tokens": 11, "completion_tokens": 5}})

    def _create(**payload: Any) -> SimpleNamespace:
        captured.clear(); captured.update(payload); return result

    client = SimpleNamespace(responses=SimpleNamespace(create=_create))
    monkeypatch.setattr(openai_module, "OpenAIClientFactory", lambda *_: SimpleNamespace(create=lambda *_a, **_k: client))
    monkeypatch.setattr(openai_module, "_openai", SimpleNamespace())
    provider = openai_module.OpenAIProvider(_make_config({"request_kwargs": {"stream": False}, "response_format": {"type": "json_object"}}))
    request = ProviderRequest(model="gpt-4o", prompt="hello", max_tokens=64, temperature=0.2, top_p=0.5, stop=("END",), timeout_s=5, options={"stream": True, "metadata": {"k": "v"}})
    response = provider.invoke(request)
    assert captured["model"] == "gpt-4o" and captured["stream"] is True and captured["metadata"] == {"k": "v"}
    assert captured["max_output_tokens"] == 64 and response.text == "generated"
    assert response.token_usage.prompt == 11 and response.token_usage.completion == 5


def test_openai_provider_raises_non_retriable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_KEY", "sk-test")

    class _SDKRateLimitError(Exception):
        pass

    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_payload: (_ for _ in ()).throw(_SDKRateLimitError("limit"))))
    monkeypatch.setattr(openai_module, "OpenAIClientFactory", lambda *_: SimpleNamespace(create=lambda *_a, **_k: client))
    monkeypatch.setattr(openai_module, "_openai", SimpleNamespace(RateLimitError=_SDKRateLimitError))
    provider = openai_module.OpenAIProvider(_make_config())
    with pytest.raises(RateLimitError):
        provider.invoke(ProviderRequest(model="gpt-4o"))


@pytest.mark.parametrize(("response", "expected"), [
    (SimpleNamespace(output_text="  text  "), "  text  "),
    ({"choices": [{"message": {"content": "from message"}}]}, "from message"),
    ({"choices": [{"message": {"content": [{"text": "part1"}, {"text": "part2"}]}}]}, "part1part2"),
    ({}, ""),
])
def test_extract_text_from_response_table(response: Any, expected: str) -> None:
    assert extract_text_from_response(response) == expected


@pytest.mark.parametrize(("usage", "prompt", "output", "expected"), [
    ({"prompt_tokens": 7, "completion_tokens": 3}, "", "", (7, 3)),
    (SimpleNamespace(input_tokens=0, output_tokens=0), "foo bar", "baz", (2, 1)),
    (None, "single", "", (1, 0)),
])
def test_extract_usage_tokens_table(usage: Any, prompt: str, output: str, expected: tuple[int, int]) -> None:
    assert extract_usage_tokens(SimpleNamespace(usage=usage), prompt, output) == expected


@given(st.lists(st.text(min_size=1, max_size=16), min_size=1, max_size=5))
def test_extract_text_streaming_fragments(fragments: list[str]) -> None:
    response = SimpleNamespace(output=[{"content": [{"text": chunk}]} for chunk in fragments])
    assert extract_text_from_response(response) == "".join(fragments)
