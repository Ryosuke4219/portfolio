from __future__ import annotations

from pathlib import Path

import adapter.cli as cli_module
from adapter.cli.prompts import run_prompts

from .test_cli_single_prompt import echo_provider  # noqa: F401 - fixture re-export


def test_cli_prompt_invalid_jsonl(echo_provider, tmp_path: Path, capfd) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: fake\nmodel: dummy\nauth_env: NONE\n",
        encoding="utf-8",
    )

    prompts_path = tmp_path / "prompts.jsonl"
    prompts_path.write_text("{}\n", encoding="utf-8")

    exit_code = run_prompts(
        [
            "--provider",
            str(config_path),
            "--prompts",
            str(prompts_path),
            "--lang",
            "en",
        ],
        provider_factory=cli_module.ProviderFactory,
    )

    captured = capfd.readouterr()
    assert exit_code == cli_module.EXIT_INPUT_ERROR
    assert "jsonl_invalid_object" in captured.err
