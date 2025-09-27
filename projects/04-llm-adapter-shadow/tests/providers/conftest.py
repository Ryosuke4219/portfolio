from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def provider_request_model() -> str:
    return "gemini:test-model"
