from __future__ import annotations

from pathlib import Path

import pytest

import adapter.cli as cli_module


def test_cli_auth_env_accepts_literal_api_key(
    echo_provider,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: FAKE_API_KEY\n"
            "api_key: sk-demo\n"
            "max_tokens: 128\n"
        ),
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
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.prompt == "hello"


def test_cli_auth_env_accepts_options_api_key(
    echo_provider,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: FAKE_API_KEY\n"
            "max_tokens: 128\n"
            "options:\n"
            "  api_key: sk-config\n"
        ),
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
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.prompt == "hello"


def test_cli_literal_api_key_option(
    echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
            "max_tokens: 128\n"
            "options:\n"
            "  foo: bar\n"
            "  api_key: sk-config\n"
        ),
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--provider-option",
            "api_key=sk-inline",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.options["api_key"] == "sk-inline"
    assert request.options["foo"] == "bar"
    assert set(request.options) == {"foo", "api_key"}


def test_cli_missing_api_key_en(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: TEST_KEY\n",
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--lang",
            "en",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 3
    assert "API key is missing" in captured.err


def test_cli_accepts_auth_env_alias(
    echo_provider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: TEST_KEY\n"
            "max_tokens: 128\n"
            "options:\n  foo: bar\n"
            "env:\n  TEST_KEY: TEST_KEY_ALIAS\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("TEST_KEY", raising=False)
    monkeypatch.setenv("TEST_KEY_ALIAS", "alias-value")

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
    assert len(echo_provider.requests) == 1
    assert "API key is missing" not in captured.err
    assert "API キーが未設定です" not in captured.err


def test_cli_accepts_auth_env_alias_lower_case(
    echo_provider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: TEST_KEY\n"
            "max_tokens: 128\n"
            "options:\n  foo: bar\n"
            "env:\n  TEST_KEY: test_key_alias\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("TEST_KEY", raising=False)
    monkeypatch.delenv("test_key_alias", raising=False)

    exit_code = cli_module.main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 3
    assert (
        "API キーが未設定です" in captured.err
        or "API key is missing" in captured.err
    )

    echo_provider.requests = []
    monkeypatch.setenv("test_key_alias", "alias-value")

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
    assert "API key is missing" not in captured.err
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
