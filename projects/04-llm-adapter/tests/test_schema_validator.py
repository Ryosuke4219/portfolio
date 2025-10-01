from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapter.core.execution.guards import _SchemaValidator


def _write_schema(tmp_path: Path, schema: dict[str, object]) -> Path:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    return path


def test_validate_accepts_valid_payload(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "number"},
        },
    }
    validator = _SchemaValidator(_write_schema(tmp_path, schema))

    payload = json.dumps({"name": "alice", "age": 30})

    validator.validate(payload)


def test_validate_raises_on_type_mismatch(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {"age": {"type": "number"}},
    }
    validator = _SchemaValidator(_write_schema(tmp_path, schema))

    with pytest.raises(ValueError) as excinfo:
        validator.validate(json.dumps({"age": "thirty"}))

    assert "is not of type" in str(excinfo.value)


def test_validate_detects_missing_nested_key(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "required": ["config"],
        "properties": {
            "config": {
                "type": "object",
                "required": ["nested"],
                "properties": {"nested": {"type": "string"}},
            }
        },
    }
    validator = _SchemaValidator(_write_schema(tmp_path, schema))

    with pytest.raises(ValueError) as excinfo:
        validator.validate(json.dumps({"config": {}}))

    assert "required property" in str(excinfo.value)
