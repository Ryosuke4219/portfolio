import sys
import warnings
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _fast_mock_provider_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.time.sleep", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _suppress_provider_response_alias_deprecations() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"ProviderResponse\.input_tokens is deprecated and will be removed",
            category=DeprecationWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"ProviderResponse\.output_tokens is deprecated and will be removed",
            category=DeprecationWarning,
        )
        yield
