from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

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


@pytest.mark.usefixtures("make_provider_request")
class TestGeminiProviderErrors:
    def test_skips_without_api_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_provider_request: Callable[..., ProviderRequest],
        provider_request_model: str,
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "")
        stub_module = SimpleNamespace(Client=lambda **_: SimpleNamespace(models=None, responses=None))
        monkeypatch.setattr(gemini_module, "genai", stub_module, raising=False)

        provider = GeminiProvider("gemini-2.5-flash")

        with pytest.raises(ProviderSkip) as excinfo:
            provider.invoke(make_provider_request(model=provider_request_model))

        assert excinfo.value.reason is SkipReason.MISSING_GEMINI_API_KEY

    def test_translates_rate_limit(
        self,
        make_provider_request: Callable[..., ProviderRequest],
    ) -> None:
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
            provider.invoke(make_provider_request())

    def test_translates_rate_limit_status_object(
        self,
        make_provider_request: Callable[..., ProviderRequest],
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
            provider.invoke(make_provider_request())

    def test_preserves_rate_limit_error_instances(
        self,
        make_provider_request: Callable[..., ProviderRequest],
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
            provider.invoke(make_provider_request())

        assert excinfo.value is raised_error

    def test_translates_timeout_status_object(
        self,
        make_provider_request: Callable[..., ProviderRequest],
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
            provider.invoke(make_provider_request())

    def test_preserves_timeout_error_instances(
        self,
        make_provider_request: Callable[..., ProviderRequest],
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
            provider.invoke(make_provider_request())

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
    def test_translates_http_errors(
        self,
        status_code: int,
        expected: type[Exception],
        make_provider_request: Callable[..., ProviderRequest],
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
            provider.invoke(make_provider_request())
