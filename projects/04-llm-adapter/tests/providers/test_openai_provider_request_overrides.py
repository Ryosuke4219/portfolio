from __future__ import annotations

from collections.abc import Sequence
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
from adapter.core.provider_spi import ProviderRequest


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text="call", usage={"input_tokens": 3, "output_tokens": 2})


def _provider_config(tmp_path: Path, mode: str) -> ProviderConfig:
    config_path = tmp_path / "openai.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider="openai",
        endpoint=None,
        model="gpt-test",
        auth_env="OPENAI_API_KEY",
        seed=0,
        temperature=0.7,
        top_p=0.6,
        max_tokens=128,
        timeout_s=30,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={
            "api": mode,
            "system_prompt": "config system",
            "request_kwargs": {
                "stream": False,
                "seed": 1,
                "stop": ["config-stop"],
                "temperature": 0.5,
                "response_format": {"type": "text"},
            },
            "response_format": {"type": "json_object"},
        },
    )


def _install_client(monkeypatch: pytest.MonkeyPatch, module: Any, attr_path: Sequence[str], recorder: _Recorder) -> None:
    class _FactoryStub:
        def __init__(self, _openai: Any) -> None:
            self.calls: list[tuple[str, Any, Any, Any]] = []

        def create(
            self,
            api_key: str,
            config: ProviderConfig,
            endpoint_url: str | None,
            default_headers: Any,
        ) -> Any:
            self.calls.append((api_key, config, endpoint_url, default_headers))
            client: Any = SimpleNamespace()
            cursor = client
            for name in attr_path[:-1]:
                child = SimpleNamespace()
                setattr(cursor, name, child)
                cursor = child
            setattr(cursor, attr_path[-1], recorder)
            return client

    monkeypatch.setattr(module, "OpenAIClientFactory", _FactoryStub, raising=False)


@pytest.mark.parametrize(
    ("mode", "attr_path", "payload_key"),
    [
        ("responses", ("responses", "create"), "input"),
        ("chat_completions", ("chat", "completions", "create"), "messages"),
        ("completions", ("completions", "create"), "prompt"),
    ],
)
def test_openai_provider_applies_request_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str, attr_path: Sequence[str], payload_key: str
) -> None:
    module = importlib.import_module("adapter.core.providers.openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(module, "_openai", object(), raising=False)
    recorder = _Recorder()
    _install_client(monkeypatch, module, attr_path, recorder)
    config = _provider_config(tmp_path, mode)
    provider = module.OpenAIProvider(config)
    request = ProviderRequest(
        model="gpt-test",
        prompt="latest question",
        messages=[
            {"role": "system", "content": "req system"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "previous"},
            {"role": "user", "content": "latest question"},
        ],
        temperature=0.2,
        top_p=0.9,
        stop=("halt", "done"),
        timeout_s=12.5,
        options={
            "stream": True,
            "response_format": {"type": "json_schema", "json_schema": {"name": "Data"}},
            "seed": 99,
            "extra": "value",
        },
    )

    response = provider.invoke(request)

    assert response.text == "call"
    assert recorder.calls, "create must be invoked"
    kwargs = recorder.calls[0]
    assert kwargs["model"] == "gpt-test"
    assert kwargs["stream"] is True
    assert kwargs["seed"] == 99
    assert kwargs["extra"] == "value"
    assert kwargs["stop"] == ("halt", "done")
    assert kwargs["temperature"] == pytest.approx(0.2)
    assert kwargs["top_p"] == pytest.approx(0.9)
    assert kwargs["timeout"] == pytest.approx(12.5)
    if payload_key == "input":
        texts = [
            fragment["text"]
            for message in kwargs[payload_key]
            for fragment in message.get("content", [])
            if isinstance(fragment, dict) and fragment.get("type") == "text"
        ]
        assert texts[:2] == ["config system", "req system"]
        assert texts[-2:] == ["previous", "latest question"]
    elif payload_key == "messages":
        roles = [entry["role"] for entry in kwargs[payload_key]]
        contents = [entry["content"] for entry in kwargs[payload_key]]
        assert roles == ["system", "user", "assistant", "user"]
        assert contents[-1] == "latest question"
    else:
        assert "config system" in kwargs[payload_key]
        assert "latest question" in kwargs[payload_key]
    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Data"},
    }
