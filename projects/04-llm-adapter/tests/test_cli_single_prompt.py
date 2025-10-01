import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import adapter.cli as cli_module
from adapter.core import providers as provider_module


def _install_provider_factory(monkeypatch, provider_cls: type) -> None:
    factory = type(
        "Factory", (), {"create": staticmethod(lambda cfg: provider_cls(cfg))}
    )
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)


class EchoProvider:
    def __init__(self, config):
        self.config = config

    def generate(self, prompt: str) -> provider_module.ProviderResponse:
        return provider_module.ProviderResponse(
            output_text=f"echo:{prompt}",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


@pytest.fixture
def echo_provider(monkeypatch):
    _install_provider_factory(monkeypatch, EchoProvider)


@pytest.fixture
def install_provider(monkeypatch):
    def _install(provider_cls: type) -> None:
        _install_provider_factory(monkeypatch, provider_cls)

    return _install


def test_cli_help_smoke() -> None:
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.check_output(
        [sys.executable, "-m", "adapter.cli", "-h"], text=True, env=env
    )
    assert "llm-adapter" in out


def test_cli_fake_provider(echo_provider, tmp_path: Path, capfd) -> None:
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
            "hello",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out


def test_cli_json_log_prompts(echo_provider, tmp_path: Path, capfd) -> None:
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
            "hello",
            "--format",
            "json",
            "--log-prompts",
        ]
    )
    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload[0]["prompt"] == "hello"


def test_cli_json_without_prompts(echo_provider, tmp_path: Path, capfd) -> None:
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
            "hello",
            "--format",
            "json",
        ]
    )
    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert "prompt" not in payload[0]


def test_cli_missing_api_key_en(monkeypatch, tmp_path: Path, capfd) -> None:
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


def test_cli_unknown_provider(tmp_path: Path, capfd) -> None:
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


def test_cli_rate_limit_exit_code(install_provider, tmp_path: Path, capfd) -> None:
    class FailingProvider:
        def __init__(self, config):
            self.config = config

        def generate(self, prompt):  # pragma: no cover - 呼ばれない
            raise RuntimeError("429 rate limit exceeded")

    install_provider(FailingProvider)

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
            "hello",
            "--lang",
            "ja",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 6
    assert "レート" in captured.err or "rate" in captured.err.lower()
