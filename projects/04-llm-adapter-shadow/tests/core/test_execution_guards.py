from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = PROJECT_ROOT / "04-llm-adapter"
GUARDS_PATH = ADAPTER_PATH / "adapter" / "core" / "execution" / "guards.py"


@pytest.mark.usefixtures("monkeypatch")
def test_schema_validator_imports_without_jsonschema(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "_guards_missing_jsonschema"
    sys.modules.pop(module_name, None)

    path_finder = importlib.machinery.PathFinder

    def _fake_find_spec(
        name: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if name == "jsonschema":
            return None
        return path_finder.find_spec(name, path, target)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    spec = importlib.util.spec_from_file_location(module_name, GUARDS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    validator = module._SchemaValidator(None)
    validator.validate("  ")

