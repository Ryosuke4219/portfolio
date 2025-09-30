from __future__ import annotations

import importlib
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_path = str(PROJECT_ROOT)
if project_path not in sys.path:
    sys.path.insert(0, project_path)

# Ensure the canonical adapter package is loaded before shadow paths can override it.
importlib.import_module("adapter")

SHADOW_ROOT = PROJECT_ROOT.parent / "04-llm-adapter-shadow"
if SHADOW_ROOT.exists():
    shadow_path = str(SHADOW_ROOT)
    if shadow_path not in sys.path:
        sys.path.append(shadow_path)


def pytest_configure(config):  # pragma: no cover - pytest hook
    if config.pluginmanager.hasplugin("asyncio"):
        config.option.asyncio_default_fixture_loop_scope = "function"
