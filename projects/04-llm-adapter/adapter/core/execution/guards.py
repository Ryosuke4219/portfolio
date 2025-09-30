"""Execution guard utilities for runner execution."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from time import perf_counter, sleep


class _TokenBucket:
    def __init__(self, rpm: int | None) -> None:
        self.capacity = rpm or 0
        self.tokens = float(self.capacity)
        self.updated = perf_counter()
        self.lock = Lock()

    def acquire(self) -> None:
        if self.capacity <= 0:
            return
        refill_rate = self.capacity / 60.0
        while True:
            with self.lock:
                now = perf_counter()
                elapsed = now - self.updated
                if elapsed > 0:
                    self.tokens = min(
                        float(self.capacity), self.tokens + elapsed * refill_rate
                    )
                    self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
            sleep(max(1.0 / max(self.capacity, 1), 0.01))


class _SchemaValidator:
    def __init__(self, schema_path: Path | None) -> None:
        self.schema: dict[str, object] | None = None
        if schema_path and schema_path.exists():
            with schema_path.open("r", encoding="utf-8") as fp:
                self.schema = json.load(fp)

    def validate(self, payload: str) -> None:
        if self.schema is None or not payload.strip():
            return
        data = json.loads(payload)
        required = self.schema.get("required") if isinstance(self.schema, dict) else None
        if isinstance(required, list):
            missing = [field for field in required if field not in data]
            if missing:
                raise ValueError(f"missing required fields: {', '.join(missing)}")
        expected_type = self.schema.get("type") if isinstance(self.schema, dict) else None
        if expected_type == "object" and not isinstance(data, dict):
            raise ValueError("schema type mismatch: expected object")


__all__ = ["_TokenBucket", "_SchemaValidator"]
