from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PYTEST_RUNNER_RETRY_DIRECT") == "1",
    reason="avoid recursive subprocess collection during runner_retry verification",
)


def test_runner_retry_collection_via_pytest() -> None:
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTEST_RUNNER_RETRY_DIRECT": "1"}
    ignore_flags = [
        "--ignore=projects/04-llm-adapter-shadow/tests",
        "--ignore=tests/shadow",
    ]
    addopts = env.get("PYTEST_ADDOPTS", "")
    for flag in ignore_flags:
        if flag not in addopts:
            addopts = f"{addopts} {flag}".strip()
    env["PYTEST_ADDOPTS"] = addopts
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
