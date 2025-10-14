from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import adapter.cli as cli_module


def test_cli_help_smoke() -> None:
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.check_output(
        [sys.executable, "-m", "adapter.cli", "-h"], text=True, env=env
    )
    assert "llm-adapter" in out


def test_cli_fake_provider(echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
            "max_tokens: 128\n"
            "options:\n  foo: bar\n"
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
    assert request.max_tokens == 128
    assert request.options == {"foo": "bar"}


def test_cli_model_override_argument(
    echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy-config\n"
            "auth_env: NONE\n"
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
            "--model",
            "cli-model",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.prompt == "hello"
    assert request.model == "cli-model"


def test_run_prompts_model_override_argument(
    echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy-config\n"
            "auth_env: NONE\n"
            "max_tokens: 64\n"
        ),
        encoding="utf-8",
    )

    exit_code = cli_module.run_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--model",
            "cli-model",
        ],
        provider_factory=cli_module.ProviderFactory,
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.prompt == "hello"
    assert request.model == "cli-model"
    assert len(echo_provider.configs) == 1
    config = echo_provider.configs[0]
    assert config.model == "cli-model"
    assert config.raw.get("model") == "cli-model"


@pytest.mark.parametrize(
    ("metadata_block", "expected"),
    [
        ("metadata:\n  run_id: cli-demo\n", {"run_id": "cli-demo"}),
        ("metadata: cli-demo\n", None),
    ],
    ids=["mapping", "non_mapping_ignored"],
)
def test_cli_passes_metadata(
    echo_provider,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    metadata_block: str,
    expected: dict[str, str] | None,
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


def test_cli_json_log_prompts(
    echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
            "max_tokens: 128\n"
            "options:\n  foo: bar\n"
        ),
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


def test_cli_provider_option_coerces_types(
    echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
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
            "--provider-option",
            "stream=true",
            "--provider-option",
            "max_tokens=42",
        ]
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.options["stream"] is True
    assert request.options["max_tokens"] == 42
    assert isinstance(request.options["max_tokens"], int)


def test_run_prompts_provider_option_coerces_types(
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
            "stream=true",
            "--provider-option",
            "max_tokens=42",
        ],
        provider_factory=cli_module.ProviderFactory,
    )
    captured = capfd.readouterr()
    assert exit_code == 0
    assert "echo:hello" in captured.out
    assert len(echo_provider.requests) == 1
    request = echo_provider.requests[0]
    assert request.options["foo"] == "bar"
    assert request.options["stream"] is True
    assert request.options["max_tokens"] == 42
    assert isinstance(request.options["max_tokens"], int)


def test_cli_json_without_prompts(
    echo_provider, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        (
            "provider: fake\n"
            "model: dummy\n"
            "auth_env: NONE\n"
            "max_tokens: 128\n"
            "options:\n  foo: bar\n"
        ),
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
