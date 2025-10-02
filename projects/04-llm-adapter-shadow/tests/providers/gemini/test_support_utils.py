from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("adapter.core.errors")
pytest.importorskip("adapter.core.providers.gemini_support")

from adapter.core.errors import RateLimitError as CoreRateLimitError
from adapter.core.providers import gemini_support


def test_normalize_gemini_exception_status_mapping() -> None:
    class _ResourceExhaustedError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.status_code = 429

    normalized = gemini_support.normalize_gemini_exception(_ResourceExhaustedError())

    assert isinstance(normalized, CoreRateLimitError)
    assert str(normalized) == "Gemini API のクォータ制限に達しました"


def test_extract_usage_prefers_usage_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(input_tokens=11, output_tokens=5)
    )

    prompt_tokens, output_tokens = gemini_support.extract_usage(
        response, "ignored", "response text"
    )

    assert prompt_tokens == 11
    assert output_tokens == 5


def test_extract_usage_estimates_when_missing_metadata() -> None:
    response = SimpleNamespace(usage_metadata=None)

    prompt_tokens, output_tokens = gemini_support.extract_usage(
        response, "prompt with four words", "three tokens here"
    )

    assert prompt_tokens == 4
    assert output_tokens == 3


def test_extract_output_text_prefers_text_field() -> None:
    response = SimpleNamespace(text=" direct text ")

    assert gemini_support.extract_output_text(response) == " direct text "


def test_extract_output_text_falls_back_to_candidates() -> None:
    response = SimpleNamespace(
        candidates=[
            {"text": ""},
            SimpleNamespace(text="candidate text"),
        ]
    )

    assert gemini_support.extract_output_text(response) == "candidate text"
