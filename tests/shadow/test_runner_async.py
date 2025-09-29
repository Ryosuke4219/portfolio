"""pytest shim to expose shadow async runner tests at the repository root."""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
    / "projects"
    / "04-llm-adapter-shadow"
)
_REAL_TEST_PATH = _PROJECT_ROOT / "tests" / "shadow" / "test_runner_async.py"

# Ensure the shadow adapter's ``src`` package is importable when executing from the
# repository root.
sys.path.insert(0, str(_PROJECT_ROOT))

if not _REAL_TEST_PATH.exists():
    raise FileNotFoundError(f"Shadow async runner tests not found at {_REAL_TEST_PATH}")

_SOURCE = _REAL_TEST_PATH.read_text(encoding="utf-8")
exec(compile(_SOURCE, str(_REAL_TEST_PATH), "exec"), globals())
