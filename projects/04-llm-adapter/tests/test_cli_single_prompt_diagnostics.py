# ruff: noqa: I001

"""Diagnostics and error classification tests for the single prompt CLI."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import adapter.cli as cli_module
from adapter.cli import (
    prompt_runner,
    prompts as prompts_module,
)
from adapter.core import providers as provider_module
from adapter.core.models import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)


def test_prompt_runner_provider_response_tokens() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.last_request: provider_module.ProviderRequest | None = None

        def generate(self, prompt: str) -> provider_module.ProviderResponse:  # pragma: no cover - 旧 API 経由
            raise AssertionError("generate() は使用しないでください")

        def invoke(
            self, request: provider_module.ProviderRequest
        ) -> provider_module.ProviderResponse:
            self.last_request = request
            return provider_module.ProviderResponse(
                output_text=f"echo:{request.prompt}",
                input_tokens=3,
                output_tokens=2,
                latency_ms=5,
            )

    provider = FakeProvider()
    config = ProviderConfig(
        path=Path("provider.yml"),
        schema_version=None,
        provider="fake",
        endpoint=None,
        model="dummy",
        auth_env=None,
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        timeout_s=30,
        retries=RetryConfig(),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={"options": {"foo": "bar"}},
    )

    def classify_error(
        exc: Exception, cfg: ProviderConfig, lang: str
    ) -> tuple[str, str]:
        return ("", "")

    results = asyncio.run(
        prompt_runner.execute_prompts(
            ["hello"],
            provider,
            config,
            concurrency=1,
            rpm=0,
            lang="ja",
            classify_error=classify_error,
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.output_text == "echo:hello"
    assert result.metric.input_tokens == 3
    assert result.metric.output_tokens == 2
    assert result.response is not None
    assert result.response.output_text == "echo:hello"
    assert provider.last_request is not None
    assert provider.last_request.prompt == "hello"
    assert provider.last_request.max_tokens == 16
    assert provider.last_request.options == {"foo": "bar"}


def test_classify_error_rate_limit_status_code() -> None:
    config = SimpleNamespace(provider="fake", auth_env="NONE")

    class RateLimitedError(Exception):
        status_code = 429

    message, kind = prompts_module._classify_error(
        RateLimitedError("Too many requests"), config, "ja"
    )
    assert kind == "rate"
    assert message == prompts_module._msg("ja", "rate_limited")


def test_classify_error_system_exit_provider_error() -> None:
    config = SimpleNamespace(provider="fake", auth_env="NONE")
    message, kind = prompts_module._classify_error(SystemExit("fatal"), config, "ja")
    assert kind == "provider"
    assert message == prompts_module._msg("ja", "provider_error", error="fatal")


def test_cli_doctor(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dummy", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setenv("LLM_ADAPTER_RPM", "120")

    fake_dotenv = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    monkeypatch.setattr(cli_module.socket, "gethostbyname", lambda host: "127.0.0.1")

    class DummyHTTPS:
        def __init__(self, host, timeout=0):
            self.host = host
            self.timeout = timeout

        def request(self, method, path):
            return None

        def getresponse(self):
            class Resp:
                status = 200

            return Resp()

        def close(self):
            return None

    monkeypatch.setattr(cli_module.http.client, "HTTPSConnection", DummyHTTPS)

    exit_code = cli_module.main(["doctor", "--lang", "en"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "All checks passed" in captured.out
