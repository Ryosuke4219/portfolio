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
    requests: list[provider_module.ProviderRequest] = []

    def __init__(self, config):
        self.config = config

    def generate(self, prompt: str) -> provider_module.ProviderResponse:  # pragma: no cover - 旧 API 経由
        raise AssertionError("generate() は使用しないでください")

    def invoke(
        self, request: provider_module.ProviderRequest
    ) -> provider_module.ProviderResponse:
        self.__class__.requests.append(request)
        return provider_module.ProviderResponse(
            output_text=f"echo:{request.prompt}",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


@pytest.fixture
def echo_provider(monkeypatch):
    EchoProvider.requests = []
    _install_provider_factory(monkeypatch, EchoProvider)
    return EchoProvider


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
        "provider: fake\nmodel: dummy\nauth_env: NONE\nmax_tokens: 128\noptions:\n  foo: bar\n",
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
    assert request.max_tokens == 128
    assert request.options == {"foo": "bar"}


@pytest.mark.parametrize(
    ("metadata_block", "expected"),
    [
        ("metadata:\n  run_id: cli-demo\n", {"run_id": "cli-demo"}),
        ("metadata: cli-demo\n", None),
    ],
    ids=["mapping", "non_mapping_ignored"],
)
def test_cli_passes_metadata(
    echo_provider, tmp_path: Path, capfd, metadata_block: str, expected: dict[str, str] | None
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
            "max_tokens: 128\n"
            "options:\n  foo: bar\n"
            f"{metadata_block}"
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
    if expected is None:
        assert request.metadata is None
    else:
        assert request.metadata == expected


def test_cli_json_log_prompts(echo_provider, tmp_path: Path, capfd) -> None:
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
            "--format",
            "json",
            "--log-prompts",
        ]
    )
    captured = capfd.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload[0]["prompt"] == "hello"


def test_cli_auth_env_accepts_literal_api_key(
    echo_provider, tmp_path: Path, capfd, monkeypatch: pytest.MonkeyPatch
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


def test_cli_literal_api_key_option(
    echo_provider, tmp_path: Path, capfd
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


def test_cli_json_without_prompts(echo_provider, tmp_path: Path, capfd) -> None:
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


def test_cli_accepts_auth_env_alias(
    echo_provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd
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
    echo_provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd
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

    EchoProvider.requests = []
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


def test_cli_openrouter_env_literal_credentials(
    echo_provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd
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
    echo_provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd
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
    assert exit_code == 6
    assert "レート" in captured.err or "rate" in captured.err.lower()
