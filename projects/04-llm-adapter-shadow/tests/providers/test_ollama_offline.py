from __future__ import annotations

from typing import Any

import pytest

from src.llm_adapter.errors import ProviderSkip
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.ollama import OllamaProvider
from tests.helpers import fakes


def test_ollama_offline_skips_without_custom_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "1")

    provider = OllamaProvider("llama3", auto_pull=False)

    with pytest.raises(ProviderSkip):
        provider.invoke(ProviderRequest(model="llama3", prompt="hi"))


def test_ollama_offline_allows_fake_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ADAPTER_OFFLINE", "1")

    class Session(fakes.FakeSession):
        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> fakes.FakeResponse:
            self.calls.append((url, json, stream))
            if url.endswith("/api/show"):
                return fakes.FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                return fakes.FakeResponse(
                    status_code=200,
                    payload={
                        "message": {"content": "ok"},
                        "prompt_eval_count": 1,
                        "eval_count": 2,
                        "done_reason": "stop",
                    },
                )
            raise AssertionError(f"unexpected url: {url}")

    session = Session()
    provider = OllamaProvider("llama3", session=session, auto_pull=False, host="http://localhost")

    response = provider.invoke(ProviderRequest(model="llama3", prompt="hi"))

    assert response.text == "ok"
    assert response.token_usage.prompt == 1
    assert response.token_usage.completion == 2
    assert response.finish_reason == "stop"
