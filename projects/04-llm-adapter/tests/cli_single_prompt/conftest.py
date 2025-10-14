from __future__ import annotations

import pytest

import adapter.cli as cli_module
from adapter.core import providers as provider_module
from adapter.core.config import ProviderConfig


def _install_provider_factory(monkeypatch: pytest.MonkeyPatch, provider_cls: type) -> None:
    factory = type("Factory", (), {"create": staticmethod(lambda cfg: provider_cls(cfg))})
    monkeypatch.setattr(provider_module, "ProviderFactory", factory)
    monkeypatch.setattr(cli_module, "ProviderFactory", factory)


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
