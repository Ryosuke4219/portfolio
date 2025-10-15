# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory
from tests.providers.openrouter.conftest import (
    FakeResponse,
    install_fake_session,
    load_openrouter_module,
    provider_config,
)


def test_openrouter_provider_supports_streaming(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is True
        assert payload is not None
        assert payload.get("stream") is True
        return FakeResponse(
            {},
            lines=[
                b"data: {\"choices\": [{\"delta\": {\"content\": \"hel\"}}]}",
                b"data: {\"choices\": [{\"delta\": {\"content\": \"lo\"}, \"finish_reason\": \"stop\"}], \"usage\": {\"prompt_tokens\": 3, \"completion_tokens\": 2}, \"model\": \"stream-model\"}",
                b"data: [DONE]",
            ],
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        provider = ProviderFactory.create(config)
        request = ProviderRequest(model=config.model, messages=[], options={"stream": True})
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "hello"
    assert response.finish_reason == "stop"
    assert response.token_usage.prompt == 3
    assert response.token_usage.completion == 2
    assert response.model == "stream-model"
    session = getattr(provider, "_session")
    session_calls = getattr(session, "calls", [])
    assert session_calls
    _url, payload, stream_flag, _timeout = session_calls[0]
    assert stream_flag is True
    assert payload is not None and payload.get("stream") is True
