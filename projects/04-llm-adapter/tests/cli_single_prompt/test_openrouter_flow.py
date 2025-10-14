from __future__ import annotations

from pathlib import Path

import pytest

import adapter.cli as cli_module


def test_cli_openrouter_env_literal_credentials(
    echo_provider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: openrouter\n"
            "model: meta-llama/llama-3.1-8b-instruct:free\n"
            "auth_env: OPENROUTER_API_KEY\n"
            "env:\n  OPENROUTER_API_KEY: sk-inline\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out


def test_cli_openrouter_inline_api_key(
    echo_provider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: openrouter\n"
            "model: meta-llama/llama-3.1-8b-instruct:free\n"
            "auth_env: OPENROUTER_API_KEY\n"
            "api_key: inline-secret\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out


def test_cli_openrouter_accepts_provider_option_api_key(
    echo_provider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: openrouter\n"
            "model: meta-llama/llama-3.1-8b-instruct:free\n"
            "auth_env: OPENROUTER_API_KEY\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--provider-option",
            "api_key=sk-demo",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.options["api_key"] == "sk-demo"
