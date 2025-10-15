# ruff: noqa: B009, B010
from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import ProviderFactory

from tests.providers.openrouter.conftest import (
    FakeResponse,
    install_fake_session,
    load_openrouter_module,
    provider_config,
)


def test_openrouter_provider_request_options_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is False
        assert payload is not None
        assert payload.get("temperature") == pytest.approx(0.7)
        assert payload.get("response_format") == "json_schema"
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "overridden"},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        config.temperature = 0.2
        config.raw["options"] = {"temperature": 0.7, "response_format": "json_schema"}
        provider = ProviderFactory.create(config)
        executor = ProviderCallExecutor(backoff=None)
        result = executor.execute(config, provider, "override options")
    finally:
        local_patch.undo()

    assert result.status == "ok"
    assert result.response.text == "overridden"


def test_openrouter_provider_request_options_take_priority_over_config_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_openrouter_module()
    captured: dict[str, Any] = {}

    def responder(
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        assert stream is False
        assert payload is not None
        captured["payload"] = payload
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "priority"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                "model": "priority-model",
            }
        )

    local_patch = install_fake_session(module, responder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        config = provider_config(tmp_path)
        config.raw["options"] = {"response_format": "config", "seed": 42}
        provider = ProviderFactory.create(config)
        request = ProviderRequest(
            model=config.model,
            messages=[],
            options={"response_format": "request", "extra": "value"},
        )
        response = provider.invoke(request)
    finally:
        local_patch.undo()

    assert response.text == "priority"
    payload = captured.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("response_format") == "request"
    assert payload.get("extra") == "value"
    assert payload.get("seed") == 42
