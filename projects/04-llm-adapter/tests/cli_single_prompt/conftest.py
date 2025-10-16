from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Protocol

import pytest

import adapter.cli as cli_module
from adapter.core import providers as provider_module
from adapter.core.config import ProviderConfig


@dataclass
class CliResult:
    exit_code: int
    stdout: str
    stderr: str


class EchoAssertion(Protocol):
    def __call__(
        self,
        result: CliResult,
        *,
        prompt: str,
        output_contains: str | None = None,
        check_output: bool = ...,
    ) -> provider_module.ProviderRequest:
        ...


class ConfigAssertion(Protocol):
    def __call__(self, *, model: str | None = None) -> ProviderConfig:
        ...


def _install_provider_factory(monkeypatch: pytest.MonkeyPatch, provider_cls: type) -> None:
    factory = type("Factory", (), {"create": staticmethod(lambda cfg: provider_cls(cfg))})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)


def _format_option_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class EchoProvider:
    requests: list[provider_module.ProviderRequest] = []
    configs: list[ProviderConfig] = []

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.__class__.configs.append(config)

    def generate(self, prompt: str) -> provider_module.ProviderResponse:  # pragma: no cover
        raise AssertionError("generate() は使用しないでください")

    def invoke(self, request: provider_module.ProviderRequest) -> provider_module.ProviderResponse:
        self.__class__.requests.append(request)
        return provider_module.ProviderResponse(
            output_text=f"echo:{request.prompt}",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


@pytest.fixture
def cli_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return env


@pytest.fixture
def run_cli_main(capfd: pytest.CaptureFixture[str]) -> Callable[[Sequence[str]], CliResult]:
    def _run(args: Sequence[str]) -> CliResult:
        exit_code = cli_module.main(list(args))
        captured = capfd.readouterr()
        return CliResult(exit_code=exit_code, stdout=captured.out, stderr=captured.err)

    return _run


@pytest.fixture
def run_cli_prompts(capfd: pytest.CaptureFixture[str]) -> Callable[[Sequence[str]], CliResult]:
    def _run(args: Sequence[str]) -> CliResult:
        exit_code = cli_module.run_prompts(
            list(args),
            provider_factory=cli_module.ProviderFactory,
        )
        captured = capfd.readouterr()
        return CliResult(exit_code=exit_code, stdout=captured.out, stderr=captured.err)

    return _run


@pytest.fixture
def provider_config_builder(tmp_path: Path) -> Callable[..., Path]:
    def _build(
        *,
        provider: str = "fake",
        model: str = "dummy",
        auth_env: str = "NONE",
        max_tokens: int = 128,
        options: dict[str, Any] | None = None,
        metadata: dict[str, Any] | str | None = None,
        file_name: str = "provider.yml",
    ) -> Path:
        lines = [
            f"provider: {provider}",
            f"model: {model}",
            f"auth_env: {auth_env}",
            f"max_tokens: {max_tokens}",
        ]
        if options:
            lines.append("options:")
            for key, value in options.items():
                lines.append(f"  {key}: {_format_option_value(value)}")
        if metadata is not None:
            if isinstance(metadata, dict):
                lines.append("metadata:")
                for key, value in metadata.items():
                    lines.append(f"  {key}: {_format_option_value(value)}")
            else:
                lines.append(f"metadata: {_format_option_value(metadata)}")
        lines.append("")
        content = "\n".join(lines)
        path = tmp_path / file_name
        path.write_text(content, encoding="utf-8")
        return path

    return _build


@pytest.fixture
def expect_successful_echo(
    echo_provider: type[EchoProvider],
) -> EchoAssertion:
    def _expect(
        result: CliResult,
        *,
        prompt: str,
        output_contains: str | None = None,
        check_output: bool = True,
    ) -> provider_module.ProviderRequest:
        assert result.exit_code == 0
        if check_output:
            expected = output_contains if output_contains is not None else f"echo:{prompt}"
            if expected:
                assert expected in result.stdout
        assert len(echo_provider.requests) == 1
        request = echo_provider.requests[0]
        assert request.prompt == prompt
        return request

    return _expect


@pytest.fixture
def expect_single_config(
    echo_provider: type[EchoProvider],
) -> ConfigAssertion:
    def _expect(*, model: str | None = None) -> ProviderConfig:
        assert len(echo_provider.configs) == 1
        config = echo_provider.configs[0]
        if model is not None:
            assert config.model == model
        return config

    return _expect


@pytest.fixture
def echo_provider(monkeypatch: pytest.MonkeyPatch) -> type[EchoProvider]:
    EchoProvider.requests = []
    EchoProvider.configs = []
    _install_provider_factory(monkeypatch, EchoProvider)
    return EchoProvider


@pytest.fixture
def install_provider(monkeypatch: pytest.MonkeyPatch):
    def _install(provider_cls: type) -> None:
        _install_provider_factory(monkeypatch, provider_cls)

    return _install
