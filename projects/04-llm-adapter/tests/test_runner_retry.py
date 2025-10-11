from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PYTEST_RUNNER_RETRY_DIRECT") == "1",
    reason="avoid recursive subprocess collection during runner_retry verification",
)


def test_runner_retry_collection_via_pytest() -> None:
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTEST_RUNNER_RETRY_DIRECT": "1"}
    command = ["pytest", "-k", "runner_retry"]

    result = subprocess.run(
        command,
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise AssertionError(
            "pytest -k runner_retry failed", result.stdout, result.stderr
        )
