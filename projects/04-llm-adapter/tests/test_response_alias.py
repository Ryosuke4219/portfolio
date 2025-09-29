from adapter.core.providers import ProviderResponse as R
from adapter.core.providers.openai_utils import (
    extract_text_from_response,
    extract_usage_tokens,
)


def test_aliases() -> None:
    resp = R(output_text="ok", input_tokens=5, output_tokens=7, latency_ms=12)
    assert resp.text == "ok"
    usage = resp.token_usage
    assert (usage.prompt, usage.completion, usage.total) == (5, 7, 12)


def test_openai_utils_response_parsing() -> None:
    class DummyUsage:
        def __init__(self, prompt_tokens: int | None, completion_tokens: int | None) -> None:
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens

    class DummyChoice:
        def __init__(self, message: dict[str, str] | None, text: str | None = None) -> None:
            self.message = message
            self.text = text

    class DummyResponse:
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    response = DummyResponse(
        output_text="primary", usage=DummyUsage(prompt_tokens=3, completion_tokens=4)
    )
    assert extract_text_from_response(response) == "primary"
    assert extract_usage_tokens(response, "prompt", "primary") == (3, 4)

    fallback_response = DummyResponse(
        output_text="",  # 空文字を経由して choices の message.content を参照
        choices=[DummyChoice({"content": "from_message"}, text="from_choice")],
        usage={"input_tokens": 6, "output_tokens": 8},
    )
    assert extract_text_from_response(fallback_response) == "from_message"
    assert extract_usage_tokens(fallback_response, "another", "output") == (6, 8)
