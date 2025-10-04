"""pytest shim to expose shadow async runner tests at the repository root."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROJECT_ROOT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "projects"
    / "04-llm-adapter-shadow"
)
_REAL_TEST_PATH = _PROJECT_ROOT / "tests" / "shadow" / "test_runner_async.py"

# Ensure the shadow adapter's ``src`` package is importable when executing from the
# repository root.
sys.path.insert(0, str(_PROJECT_ROOT))

if not _REAL_TEST_PATH.exists():
    raise FileNotFoundError(f"Shadow async runner tests not found at {_REAL_TEST_PATH}")

_SPEC = importlib.util.spec_from_file_location(
    "shadow.tests.test_runner_async", _REAL_TEST_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Failed to load spec for {_REAL_TEST_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
    if not _name.startswith("test_"):
        continue
    _value = getattr(_MODULE, _name)
    if callable(_value):
        globals()[_name] = _value
