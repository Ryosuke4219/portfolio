from __future__ import annotations

import pytest

from ..parallel_helpers import (
    _install_recording_executor,
    _RecordingThreadPoolExecutor,
)


@pytest.fixture
def recording_executors(
    monkeypatch: pytest.MonkeyPatch,
) -> list[_RecordingThreadPoolExecutor]:
    return _install_recording_executor(monkeypatch)
