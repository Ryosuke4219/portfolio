from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from types import SimpleNamespace, TracebackType
from typing import Any, Literal, cast

from src.llm_adapter.providers import ollama as ollama_module
from src.llm_adapter.providers.gemini_client import (
    GeminiModelsAPI,
    GeminiResponsesAPI,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any] | None = None,
        lines: list[bytes] | None = None,
        iter_lines_exception: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = lines or [b"{}"]
        self._iter_lines_exception = iter_lines_exception
        self.closed = False

    def raise_for_status(self) -> None:
        if not (200 <= self.status_code < 300):
            http_error = cast(Any, ollama_module.requests_exceptions.HTTPError)
            raise http_error(response=self)

    def json(self) -> dict[str, Any]:
        return self._payload

    def iter_lines(self) -> Iterator[bytes]:
        if self._iter_lines_exception is not None:
            raise self._iter_lines_exception
        yield from self._lines

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeResponse:  # pragma: no cover - context protocol
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:  # pragma: no cover - context protocol
        self.close()
        return False


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None, bool]] = []
        self._show_calls = 0

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        """Override in subclasses."""  # pragma: no cover - patched in tests
        raise NotImplementedError


class RecordGeminiClient:
    def __init__(
        self,
        *,
        text: str = "こんにちは",
        input_tokens: int = 12,
        output_tokens: int = 7,
        extra_response_fields: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response_fields = {
            "text": text,
            "usage_metadata": SimpleNamespace(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        }
        if extra_response_fields:
            self._response_fields.update(extra_response_fields)

        class _Models:
            def __init__(self, outer: RecordGeminiClient) -> None:
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
                    if hasattr(config, "to_dict"):
                        to_dict = cast(Callable[[], dict[str, Any]], config.to_dict)
                        recorded["_config_dict"] = to_dict()
                self._outer.calls.append(recorded)
                return SimpleNamespace(**self._outer._response_fields)

        self.models: GeminiModelsAPI | None = _Models(self)
        self.responses: GeminiResponsesAPI | None = None
