from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = PROJECT_ROOT / "04-llm-adapter"
GUARDS_PATH = ADAPTER_PATH / "adapter" / "core" / "execution" / "guards.py"


def _import_guards_without_jsonschema(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module_name = "_guards_missing_jsonschema"
    sys.modules.pop(module_name, None)
    sys.modules.pop("jsonschema", None)

    path_finder = importlib.machinery.PathFinder

    def _fake_find_spec(
        name: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if name == "jsonschema":
            return None
        return path_finder.find_spec(name, path=path, target=target)

    real_import = builtins.__import__

    def _fake_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name.startswith("jsonschema"):
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    monkeypatch.setattr(builtins, "__import__", _fake_import)

    spec = importlib.util.spec_from_file_location(module_name, GUARDS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.usefixtures("monkeypatch")
def test_schema_validator_imports_without_jsonschema(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _import_guards_without_jsonschema(monkeypatch)

    validator = module._SchemaValidator(None)
    validator.validate("  ")


def test_schema_validator_requires_jsonschema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _import_guards_without_jsonschema(monkeypatch)

    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    validator = module._SchemaValidator(schema_path)

    with pytest.raises(ValueError):
        validator.validate("{}")

