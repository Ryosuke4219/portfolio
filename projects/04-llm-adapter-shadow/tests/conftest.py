import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _fast_mock_provider_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.llm_adapter.providers.mock.time.sleep", lambda *args, **kwargs: None)
