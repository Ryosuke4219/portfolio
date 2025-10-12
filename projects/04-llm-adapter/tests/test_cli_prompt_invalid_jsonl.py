from __future__ import annotations

from pathlib import Path

import pytest

import adapter.cli as cli_module
from adapter.cli.prompts import run_prompts
from adapter.core import providers as provider_module


class _EchoProvider:
    requests: list[provider_module.ProviderRequest] = []

    def __init__(self, config):
        self.config = config

    def invoke(self, request: provider_module.ProviderRequest) -> provider_module.ProviderResponse:
        self.__class__.requests.append(request)
        return provider_module.ProviderResponse(
            output_text=f"echo:{request.prompt}",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


@pytest.fixture()
def echo_provider(monkeypatch: pytest.MonkeyPatch):
    _EchoProvider.requests = []

    def _create(config):
        return _EchoProvider(config)

    factory = type("Factory", (), {"create": staticmethod(_create)})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)
    return _EchoProvider


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
