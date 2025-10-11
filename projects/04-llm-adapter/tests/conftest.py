from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
from collections.abc import Sequence
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_path = str(PROJECT_ROOT)
if project_path not in sys.path:
    sys.path.insert(0, project_path)


class _ShadowSrcFinder(importlib.abc.MetaPathFinder):
    def __init__(self, shadow_root: Path) -> None:
        self._shadow_src = shadow_root / "src"

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: object | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith("src"):
            return None
        if not self._shadow_src.exists():
            return None
        return importlib.machinery.PathFinder.find_spec(fullname, [str(self._shadow_src)])


# Ensure the canonical adapter package is loaded before shadow import hooks can override it.
importlib.import_module("adapter")

SHADOW_ROOT = PROJECT_ROOT.parent / "04-llm-adapter-shadow"
if SHADOW_ROOT.exists():
    shadow_finder = _ShadowSrcFinder(SHADOW_ROOT)
    if not any(isinstance(finder, _ShadowSrcFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, shadow_finder)


def pytest_configure(config):  # pragma: no cover - pytest hook
    if config.pluginmanager.hasplugin("asyncio"):
        config.option.asyncio_default_fixture_loop_scope = "function"
