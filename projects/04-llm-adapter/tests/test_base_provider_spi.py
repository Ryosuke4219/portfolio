
from __future__ import annotations

from pathlib import Path

from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)
import pytest

from adapter.core._provider_execution import ProviderCallExecutor
from adapter.core.provider_spi import ProviderRequest
from adapter.core.providers import BaseProvider, ProviderResponse

# Gemini プロバイダ依存モジュール
from adapter.core.providers import gemini as gemini_module


def _provider_config(tmp_path: Path, provider: str) -> ProviderConfig:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider=provider,
        endpoint=None,
        model="dummy-model",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=30,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


class _DummyProvider(BaseProvider):
    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - not used
        raise NotImplementedError


def test_base_provider_generate_propagates_config_values(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    config.max_tokens = 128
    config.temperature = 0.42
    config.top_p = 0.73
    config.timeout_s = 45

    class _AssertingProvider(_DummyProvider):
        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            assert request.max_tokens == config.max_tokens
            assert request.temperature == config.temperature
            assert request.top_p == config.top_p
            assert request.timeout_s == float(config.timeout_s)
            return ProviderResponse(text="ok", latency_ms=0)

    provider = _AssertingProvider(config)

    provider.generate("hello world")


def test_base_provider_name_returns_provider_id(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    provider = _DummyProvider(config)

    assert provider.name() == "mock-provider"


def test_base_provider_capabilities_default(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="mock-provider")
    provider = _DummyProvider(config)

    assert provider.capabilities() == {"chat"}


def test_provider_call_executor_invokes_with_request(tmp_path: Path) -> None:
    config = _provider_config(tmp_path, provider="stub-provider")
    config.max_tokens = 64
    config.temperature = 0.55
    config.top_p = 0.9
    config.timeout_s = 12

    captured: dict[str, ProviderRequest | ProviderResponse] = {}

    class _RecordingProvider(BaseProvider):
        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            captured["request"] = request
            return ProviderResponse(text="ok", latency_ms=5)

        def generate(self, prompt: str) -> ProviderResponse:  # pragma: no cover - ensure未使用
            raise AssertionError("ProviderCallExecutor は invoke を利用するべきです")

    provider = _RecordingProvider(config)
    executor = ProviderCallExecutor(backoff=None)

    result = executor.execute(config, provider, "test prompt")

    assert result.status == "ok"
    assert "request" in captured
    request = captured["request"]
    assert isinstance(request, ProviderRequest)
    assert request.model == config.model
    assert request.prompt == "test prompt"
    assert request.max_tokens == config.max_tokens
    assert request.temperature == config.temperature
    assert request.top_p == config.top_p
    assert request.timeout_s == pytest.approx(float(config.timeout_s))


def test_gemini_provider_invoke_respects_request_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _provider_config(tmp_path, provider="gemini")
    config.raw = {}

    class _StubClient:
        def __init__(self, *, api_key: str) -> None:  # pragma: no cover - 単純スタブ
            self.api_key = api_key

    class _StubGenAI:
        Client = _StubClient

    monkeypatch.setattr(gemini_module, "_genai", _StubGenAI)
    monkeypatch.setattr(gemini_module, "_resolve_api_key", lambda env: "token")

    captured: dict[str, object] = {}

    def _fake_invoke(client, model, contents, generation_config, safety_settings):  # type: ignore[no-untyped-def]
        captured.update(
            {
                "model": model,
                "contents": contents,
                "config": generation_config,
                "safety": safety_settings,
            }
        )

        class _StubResponse:
            text = "ok"
            usage_metadata = type("Usage", (), {"input_tokens": 1, "output_tokens": 1})()

        return _StubResponse()

    monkeypatch.setattr(gemini_module, "_invoke_gemini", _fake_invoke)
    monkeypatch.setattr(gemini_module, "_coerce_raw_output", lambda response: {"raw": True})

    provider = gemini_module.GeminiProvider(config)

    request = ProviderRequest(
        model="gemini-1.5-pro",
        prompt="こんにちは",
        max_tokens=33,
        temperature=0.45,
        messages=[{"role": "user", "content": "こんにちは"}],
        options={
            "generation_config": {"candidate_count": 2},
            "safety_settings": [{"category": "TEST", "threshold": "BLOCK_NONE"}],
        },
    )

    response = provider.invoke(request)

    assert response.text == "ok"
    assert captured["model"] == request.model
    assert captured["config"] == {
        "candidate_count": 2,
        "max_output_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    assert captured["contents"] == [
        {"role": "user", "parts": [{"text": "こんにちは"}]}
    ]
    assert captured["safety"] == request.options["safety_settings"]
