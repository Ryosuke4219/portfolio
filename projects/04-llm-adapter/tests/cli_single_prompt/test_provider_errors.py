from __future__ import annotations

from pathlib import Path

import pytest

import adapter.cli as cli_module
from adapter.core import providers as provider_module


def test_cli_errors_when_provider_lacks_invoke(
    install_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    class LegacyProvider:
        def __init__(self, config: provider_module.ProviderConfig):
            self.config = config

        def generate(self, prompt: str) -> provider_module.ProviderResponse:
            return provider_module.ProviderResponse(
                output_text=prompt,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
            )

    install_provider(LegacyProvider)
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "legacy",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == cli_module.EXIT_PROVIDER_ERROR
    assert "invoke(request)" in captured.err


def test_cli_errors_when_provider_factory_returns_non_invoke_provider(
    install_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    class NoInvokeProvider:
        def __init__(self, config: provider_module.ProviderConfig):
            self.config = config

    install_provider(NoInvokeProvider)
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "legacy",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == cli_module.EXIT_PROVIDER_ERROR
    assert "Provider must implement invoke(request)." in captured.err


def test_cli_unknown_provider(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: unknown\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 2
    assert "未対応" in captured.err


def test_cli_rate_limit_exit_code(
    install_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    class FailingProvider:
        def __init__(self, config: provider_module.ProviderConfig):
            self.config = config

        def invoke(self, request: provider_module.ProviderRequest) -> provider_module.ProviderResponse:
            raise RuntimeError("429 rate limit exceeded")

        def generate(self, prompt: str) -> provider_module.ProviderResponse:  # pragma: no cover
            raise RuntimeError("429 rate limit exceeded")

    install_provider(FailingProvider)

    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\nmax_tokens: 128\noptions:\n  foo: bar\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--lang",
            "ja",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == cli_module.EXIT_RATE_LIMIT
    assert "レート" in captured.err or "rate" in captured.err.lower()
