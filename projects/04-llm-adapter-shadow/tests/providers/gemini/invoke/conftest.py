from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("adapter.core.providers.gemini_support")

from src.llm_adapter.provider_spi import ProviderRequest


@pytest.fixture
def make_provider_request(
    provider_request_model: str,
) -> Callable[..., ProviderRequest]:
    def _make(**overrides: Any) -> ProviderRequest:
        payload: dict[str, Any] = {
            "prompt": "hello",
            "model": provider_request_model,
        }
        payload.update(overrides)
        return ProviderRequest(**payload)

    return _make
