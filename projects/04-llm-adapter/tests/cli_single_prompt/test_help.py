from __future__ import annotations

import subprocess
import sys


def test_cli_help_smoke(cli_subprocess_env: dict[str, str]) -> None:
    out = subprocess.check_output(
        [sys.executable, "-m", "adapter.cli", "-h"],
        text=True,
        env=cli_subprocess_env,
    )
    assert "llm-adapter" in out
