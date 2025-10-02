from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest

pytest.importorskip("adapter.core.providers.gemini_support")

from src.llm_adapter.errors import (
    AuthError,
    ProviderSkip,
    RateLimitError,
    SkipReason,
    TimeoutError,
)
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers import gemini as gemini_module
from src.llm_adapter.providers.gemini import GeminiProvider
from src.llm_adapter.providers.gemini_client import (
    GeminiModelsAPI,
    GeminiResponsesAPI,
)
from tests.helpers.fakes import RecordGeminiClient


def _maybe_attr(obj: Any, name: str) -> Any:
    return getattr(obj, name) if hasattr(obj, name) else None


def test_gemini_provider_invokes_client_with_config() -> None:
    client = RecordGeminiClient()
    provider = GeminiProvider(
        "gemini-2.5-flash",
        client=client,
        generation_config={"temperature": 0.2},
    )

    request = ProviderRequest(
        prompt="テスト",
        max_tokens=128,
        metadata={"system": "you are helpful"},
        temperature=0.4,
        top_p=0.85,
        stop=("END",),
        model="gemini-2.5-flash",
    )
    response = provider.invoke(request)

    assert response.text == "こんにちは"
    assert response.token_usage.prompt == 12
    assert response.token_usage.completion == 7
    assert response.latency_ms >= 0
    assert response.model == "gemini-2.5-flash"
    assert response.tokens_in == 12
    assert response.tokens_out == 7
    assert response.finish_reason is None
    assert response.raw is not None

    recorded = client.calls.pop()
    assert recorded["model"] == "gemini-2.5-flash"
    assert recorded["contents"][0]["role"] == "system"
    assert recorded["contents"][0]["parts"][0]["text"] == "you are helpful"
    assert recorded["contents"][1]["role"] == "user"
    recorded_config = recorded["config"]
    config_view: dict[str, Any] = {}
    config_dict = recorded.get("_config_dict")
    if isinstance(config_dict, Mapping):
        config_view.update(config_dict)
    if hasattr(recorded_config, "to_dict"):
        to_dict = cast(Callable[[], Any], recorded_config.to_dict)
        maybe = to_dict()
        if isinstance(maybe, Mapping):
            config_view.update(maybe)
    if isinstance(recorded_config, Mapping):
        config_view.update(recorded_config)

    temperature = config_view.get("temperature")
    if temperature is None:
        maybe_temp = _maybe_attr(recorded_config, "temperature")
        if maybe_temp is not None:
            temperature = maybe_temp
    max_tokens = config_view.get("max_output_tokens")
    if max_tokens is None:
        maybe_max = _maybe_attr(recorded_config, "max_output_tokens")
        if maybe_max is not None:
            max_tokens = maybe_max

    stop_sequences = config_view.get("stop_sequences")
    top_p = config_view.get("top_p")
    if top_p is None:
        maybe_top_p = _maybe_attr(recorded_config, "top_p")
        if maybe_top_p is not None:
            top_p = maybe_top_p
    if stop_sequences is None:
        maybe_stop = _maybe_attr(recorded_config, "stop_sequences")
        if maybe_stop is not None:
            stop_sequences = maybe_stop

    assert temperature == 0.2
    assert top_p == pytest.approx(0.85)
    assert stop_sequences == ["END"]
    assert max_tokens == 128
    assert isinstance(recorded["contents"], list)


def test_gemini_provider_uses_request_model_override_and_finish_reason() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.responses: GeminiResponsesAPI | None = None

            class _Models:
                def __init__(self, outer: _Client) -> None:
                    self._outer = outer

                def generate_content(
                    self,
                    *,
                    model: str,
                    contents: Sequence[Mapping[str, Any]] | None,
                    config: Any | None = None,
                ) -> SimpleNamespace:
                    recorded: dict[str, Any] = {"model": model, "contents": contents}
                    if config is not None:
                        recorded["config"] = config
                    self._outer.calls.append(recorded)
                    return SimpleNamespace(
                        text="ok",
                        usage_metadata=SimpleNamespace(input_tokens=2, output_tokens=3),
                        candidates=[SimpleNamespace(finish_reason="STOP")],
                    )

            self.models: GeminiModelsAPI | None = _Models(self)

    client = _Client()
    provider = GeminiProvider("gemini-1.5-pro", client=client)

    request = ProviderRequest(prompt="hello", model="gemini-1.5-pro-exp")
    response = provider.invoke(request)

    recorded = client.calls.pop()
    assert recorded["model"] == "gemini-1.5-pro-exp"
    assert response.model == "gemini-1.5-pro-exp"
    assert response.finish_reason == "STOP"
    assert response.tokens_in == 2
    assert response.tokens_out == 3


def test_gemini_provider_skips_without_api_key(
    monkeypatch: pytest.MonkeyPatch, provider_request_model: str
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    stub_module = SimpleNamespace(Client=lambda **_: SimpleNamespace(models=None, responses=None))
    monkeypatch.setattr(gemini_module, "genai", stub_module, raising=False)

    provider = GeminiProvider("gemini-2.5-flash")

    with pytest.raises(ProviderSkip) as excinfo:
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))

    assert excinfo.value.reason is SkipReason.MISSING_GEMINI_API_KEY


def test_gemini_provider_translates_rate_limit(provider_request_model: str) -> None:
    class _ResourceExhaustedError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.status: str = "RESOURCE_EXHAUSTED"

    class _FailingModels:
        def generate_content(
            self,
            *,
            model: str,
            contents: Sequence[Mapping[str, Any]] | None,
            config: Any | None = None,
        ) -> NoReturn:
            raise _ResourceExhaustedError()

    class _Client:
        def __init__(self) -> None:
            self.models: GeminiModelsAPI | None = _FailingModels()
            self.responses: GeminiResponsesAPI | None = None

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())

    with pytest.raises(RateLimitError):
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))


def test_gemini_provider_translates_rate_limit_status_object(
    provider_request_model: str,
) -> None:
    class _StatusCode:
        def __init__(self, name: str) -> None:
            self.name = name

        def __str__(self) -> str:
            return f"StatusCode.{self.name}"

    class _RateLimitedError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.status: _StatusCode = _StatusCode("RESOURCE_EXHAUSTED")

    class _FailingModels:
        def generate_content(
            self,
            *,
            model: str,
            contents: Sequence[Mapping[str, Any]] | None,
            config: Any | None = None,
        ) -> NoReturn:
            raise _RateLimitedError()

    class _Client:
        def __init__(self) -> None:
            self.models: GeminiModelsAPI | None = _FailingModels()
            self.responses: GeminiResponsesAPI | None = None

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())

    with pytest.raises(RateLimitError):
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))


def test_gemini_provider_preserves_rate_limit_error_instances(
    provider_request_model: str,
) -> None:
    raised_error = RateLimitError("rate limited")

    class _FailingModels:
        def generate_content(
            self,
            *,
            model: str,
            contents: Sequence[Mapping[str, Any]] | None,
            config: Any | None = None,
        ) -> NoReturn:
            raise raised_error

    class _Client:
        def __init__(self) -> None:
            self.models: GeminiModelsAPI | None = _FailingModels()
            self.responses: GeminiResponsesAPI | None = None

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())

    with pytest.raises(RateLimitError) as excinfo:
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))

    assert excinfo.value is raised_error


def test_gemini_provider_translates_timeout_status_object(
    provider_request_model: str,
) -> None:
    class _StatusCode:
        def __init__(self, name: str) -> None:
            self.name = name

        def __str__(self) -> str:
            return f"StatusCode.{self.name}"

    class _DeadlineExceededError(Exception):
        def __init__(self) -> None:
            super().__init__("timeout")
            self.code: _StatusCode = _StatusCode("DEADLINE_EXCEEDED")

    class _FailingModels:
        def generate_content(
            self,
            *,
            model: str,
            contents: Sequence[Mapping[str, Any]] | None,
            config: Any | None = None,
        ) -> NoReturn:
            raise _DeadlineExceededError()

    class _Client:
        def __init__(self) -> None:
            self.models: GeminiModelsAPI | None = _FailingModels()
            self.responses: GeminiResponsesAPI | None = None

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())

    with pytest.raises(TimeoutError):
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))


def test_gemini_provider_preserves_timeout_error_instances(
    provider_request_model: str,
) -> None:
    raised_error = TimeoutError("took too long")

    class _FailingModels:
        def generate_content(
            self,
            *,
            model: str,
            contents: Sequence[Mapping[str, Any]] | None,
            config: Any | None = None,
        ) -> NoReturn:
            raise raised_error

    class _Client:
        def __init__(self) -> None:
            self.models: GeminiModelsAPI | None = _FailingModels()
            self.responses: GeminiResponsesAPI | None = None

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())

    with pytest.raises(TimeoutError) as excinfo:
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))

    assert excinfo.value is raised_error


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (429, RateLimitError),
        (401, AuthError),
        (403, AuthError),
        (408, TimeoutError),
        (504, TimeoutError),
    ],
)
def test_gemini_provider_translates_http_errors(
    status_code: int, expected: type[Exception], provider_request_model: str
) -> None:
    class _HttpError(Exception):
        def __init__(self, code: int) -> None:
            super().__init__(f"http {code}")
            self.response = SimpleNamespace(status_code=code)

    class _FailingModels:
        def generate_content(
            self,
            *,
            model: str,
            contents: Sequence[Mapping[str, Any]] | None,
            config: Any | None = None,
        ) -> NoReturn:
            raise _HttpError(status_code)

    class _Client:
        def __init__(self) -> None:
            self.models: GeminiModelsAPI | None = _FailingModels()
            self.responses: GeminiResponsesAPI | None = None

    provider = GeminiProvider("gemini-2.5-flash", client=_Client())

    with pytest.raises(expected):
        provider.invoke(ProviderRequest(prompt="hello", model=provider_request_model))
