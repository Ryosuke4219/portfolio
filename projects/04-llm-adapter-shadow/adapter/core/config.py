"""Provider configuration loader used by the shadow test-suite."""
from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from collections.abc import Mapping, MutableMapping
from typing import Any

import yaml

__all__ = ["ConfigError", "ProviderConfig", "load_provider_config"]


class ConfigError(ValueError):
    """Raised when the provider configuration file is invalid."""


@dataclass(slots=True, frozen=True)
class ProviderConfig:
    """In-memory representation of a provider configuration."""

    schema_version: int
    provider: str
    model: str
    auth_env: str | None = None
    max_tokens: int | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        extras = dict(self.extras)
        object.__setattr__(self, "extras", extras)


def _coerce_path(config: str | Path | PathLike[str]) -> Path:
    if isinstance(config, Path):
        return config
    if isinstance(config, (str, PathLike)):
        return Path(config)
    raise ConfigError("Config path must be a string or Path instance.")


def _validate_str(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"'{field_name}' must be a non-empty string.")
    return value


def _validate_int(data: Mapping[str, Any], field_name: str, *, default: int | None = None) -> int:
    if field_name not in data:
        if default is None:
            raise ConfigError(f"'{field_name}' field is required.")
        return default
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"'{field_name}' must be an integer.")
    return value


def _optional_int(data: Mapping[str, Any], field_name: str) -> int | None:
    if field_name not in data or data[field_name] is None:
        return None
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"'{field_name}' must be an integer.")
    return value


def load_provider_config(config: str | Path) -> ProviderConfig:
    """Load and validate a provider configuration file."""

    path = _coerce_path(config)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc

    try:
        raw_data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML: {exc}") from exc

    if not isinstance(raw_data, MutableMapping):
        raise ConfigError("Configuration root must be a mapping.")

    schema_version = _validate_int(raw_data, "schema_version", default=1)
    provider = _validate_str(raw_data, "provider")
    model = _validate_str(raw_data, "model")
    auth_env = raw_data.get("auth_env")
    if auth_env is not None and (not isinstance(auth_env, str) or not auth_env):
        raise ConfigError("'auth_env' must be a non-empty string when provided.")
    max_tokens = _optional_int(raw_data, "max_tokens")

    extras = {
        key: value
        for key, value in raw_data.items()
        if key
        not in {"schema_version", "provider", "model", "auth_env", "max_tokens"}
    }

    return ProviderConfig(
        schema_version=schema_version,
        provider=provider,
        model=model,
        auth_env=auth_env,
        max_tokens=max_tokens,
        extras=extras,
    )
