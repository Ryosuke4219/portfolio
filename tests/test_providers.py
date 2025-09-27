from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "projects"
    / "04-llm-adapter-shadow"
    / "src"
    / "llm_adapter"
    / "provider_spi.py"
)

spec = importlib.util.spec_from_file_location("shadow_provider_spi", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader

sys.modules[spec.name] = module
spec.loader.exec_module(module)
ProviderRequest = module.ProviderRequest


def test_provider_request_timeout_defaults_to_30_seconds() -> None:
    request = ProviderRequest(model="test-model")

    assert request.timeout == 30
    assert request.timeout_s is None


def test_provider_request_requires_model_argument() -> None:
    with pytest.raises(TypeError):
        ProviderRequest()
