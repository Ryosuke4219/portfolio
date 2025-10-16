from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import adapter.cli as cli_module

pytest_plugins = ("tests.cli_single_prompt.conftest",)


class _FailingFactory:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def create(self, config: Any) -> Any:  # pragma: no cover - simple delegator
        raise self._exc


def test_run_prompts_env_missing(
    echo_provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: API_KEY\nmax_tokens: 32\n",
        encoding="utf-8",
    )

    exit_code = cli_module.run_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ],
        provider_factory=cli_module.ProviderFactory,
    )

    assert exit_code == cli_module.EXIT_ENV_ERROR


def test_run_prompts_loads_env_file(
    echo_provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd
) -> None:
    pytest.importorskip("dotenv")
    monkeypatch.delenv("API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("API_KEY=from_env\n", encoding="utf-8")
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: API_KEY\nmax_tokens: 32\n",
        encoding="utf-8",
    )

    exit_code = cli_module.run_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--env",
            str(env_path),
        ],
        provider_factory=cli_module.ProviderFactory,
    )

    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert os.getenv("API_KEY") == "from_env"


def test_run_prompts_merges_provider_options(
    echo_provider, tmp_path: Path, capfd
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
            "max_tokens: 32\n"
            "options:\n"
            "  foo: config\n"
            "  keep: value\n"
        ),
        encoding="utf-8",
    )

    exit_code = cli_module.run_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--provider-option",
            "foo=cli",
            "--provider-option",
            "extra=true",
        ],
        provider_factory=cli_module.ProviderFactory,
    )

    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    request = echo_provider.requests[0]
    assert request.options["foo"] == "cli"
    assert request.options["keep"] == "value"
    assert request.options["extra"] is True


def test_run_prompts_provider_failure(tmp_path: Path) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\nmax_tokens: 32\n",
        encoding="utf-8",
    )

    class RateLimitError(RuntimeError):
        status_code = 429

    exit_code = cli_module.run_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ],
        provider_factory=_FailingFactory(RateLimitError("429 Too Many Requests")),
    )

    assert exit_code == cli_module.EXIT_RATE_LIMIT


def test_run_prompts_missing_prompt_sources(
    echo_provider, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\nmax_tokens: 32\n",
        encoding="utf-8",
    )

    exit_code = cli_module.run_prompts(
        [
            "--provider",
            str(config_path),
        ],
        provider_factory=cli_module.ProviderFactory,
    )

    captured = capsys.readouterr()
    assert exit_code == cli_module.EXIT_INPUT_ERROR
    assert "--prompt" in captured.err
