"""Execution guard utilities for runner execution."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from time import perf_counter, sleep
from types import SimpleNamespace
from typing import Any, Protocol, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from jsonschema.exceptions import ValidationError as _ValidationError
else:
    class _ValidationError(Exception):
        path: tuple[Any, ...]
        message: str


class _ValidatorProtocol(Protocol):
    def __init__(self, schema: dict[str, Any]) -> None:
        ...

    @classmethod
    def check_schema(cls, schema: dict[str, Any]) -> None:
        ...

    def validate(self, instance: Any) -> None:
        ...


class _ValidatorsModule(Protocol):
    def validator_for(self, schema: dict[str, Any]) -> type[_ValidatorProtocol]:
        ...


class _ExceptionsModule(Protocol):
    ValidationError: type["_ValidationError"]


class _MissingValidationError(ValueError):
    """Raised when jsonschema is required but unavailable."""

    def __init__(self) -> None:
        message = (
            "jsonschema is required to validate request payloads. Install "
            "the optional dependency to enable schema validation."
        )
        super().__init__(message)
        self.message = message
        self.path: tuple[Any, ...] = ()


class _MissingValidator:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    @classmethod
    def check_schema(cls, _: dict[str, Any]) -> None:
        return None

    def validate(self, _: Any) -> None:
        raise _MissingValidationError()


class _FallbackValidators:
    @staticmethod
    def validator_for(_: dict[str, Any]) -> type[_MissingValidator]:
        return _MissingValidator


try:
    from jsonschema import exceptions as _jsonschema_exceptions
    from jsonschema import validators as _jsonschema_validators
except ImportError:
    _validators_impl: _ValidatorsModule = cast(
        _ValidatorsModule, _FallbackValidators()
    )
    _exceptions_impl: _ExceptionsModule = cast(
        _ExceptionsModule,
        SimpleNamespace(ValidationError=_MissingValidationError),
    )
else:
    _validators_impl = cast(_ValidatorsModule, _jsonschema_validators)
    _exceptions_impl = cast(_ExceptionsModule, _jsonschema_exceptions)

validators: _ValidatorsModule = _validators_impl
jsonschema_exceptions: _ExceptionsModule = _exceptions_impl


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
        self.schema: dict[str, Any] | None = None
        self._validator: _ValidatorProtocol | None = None
        if schema_path and schema_path.exists():
            with schema_path.open("r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            if isinstance(loaded, dict):
                self.schema = loaded
                validator_cls = validators.validator_for(loaded)
                validator_cls.check_schema(loaded)
                self._validator = validator_cls(loaded)

    def validate(self, payload: str) -> None:
        if self._validator is None or not payload.strip():
            return
        data = json.loads(payload)
        try:
            self._validator.validate(data)
        except jsonschema_exceptions.ValidationError as exc:
            path = " -> ".join(str(segment) for segment in exc.path)
            message = exc.message if exc.message else str(exc)
            if path:
                message = f"{message} (at {path})"
            raise ValueError(message) from None


__all__ = ["_TokenBucket", "_SchemaValidator"]
