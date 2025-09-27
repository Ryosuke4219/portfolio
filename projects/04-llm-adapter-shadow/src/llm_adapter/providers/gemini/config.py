"""Configuration helpers for Gemini runtime."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from ._sdk import gt
from ...provider_spi import ProviderRequest

__all__ = ["merge_generation_config", "prepare_generation_config"]


def merge_generation_config(
    base_config: Mapping[str, Any] | None,
    request: ProviderRequest,
) -> MutableMapping[str, Any] | None:
    """Merge provider-level configuration with request overrides."""

    config: MutableMapping[str, Any] = {}
    if base_config:
        config.update(base_config)

    option_config = None
    if request.options and isinstance(request.options, Mapping):
        option_config = request.options.get("generation_config")
    if isinstance(option_config, Mapping):
        config.update(option_config)

    if request.max_tokens and "max_output_tokens" not in config:
        config["max_output_tokens"] = int(request.max_tokens)

    if request.temperature is not None and "temperature" not in config:
        config["temperature"] = float(request.temperature)

    if request.top_p is not None and "top_p" not in config:
        config["top_p"] = float(request.top_p)

    if request.stop and "stop_sequences" not in config:
        config["stop_sequences"] = list(request.stop)

    return config or None


def prepare_generation_config(
    base_config: Mapping[str, Any] | None,
    safety_settings: Sequence[Mapping[str, Any]] | None,
) -> tuple[Any | None, Mapping[str, Any] | None]:
    """Build config objects compatible with both legacy and modern SDKs."""

    merged: dict[str, Any] = {}
    if base_config:
        merged.update(base_config)
    if safety_settings:
        merged["safety_settings"] = list(safety_settings)

    config_obj: Any | None = None
    if gt is not None:
        config_obj = gt.GenerateContentConfig(**merged)
    elif merged:
        config_obj = merged

    config_payload: Mapping[str, Any] | None = None
    if config_obj is not None:
        to_dict = getattr(config_obj, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            if isinstance(payload, Mapping) and payload:
                config_payload = payload
    if config_payload is None and merged:
        config_payload = merged

    return config_obj, config_payload
