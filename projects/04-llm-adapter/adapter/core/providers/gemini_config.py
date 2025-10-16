"""Gemini プロバイダの設定値を正規化するユーティリティ。"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from ..config import ProviderConfig

__all__ = ["prepare_generation_config", "prepare_safety_settings"]


def prepare_generation_config(config_obj: ProviderConfig) -> MutableMapping[str, Any]:
    """Prepare the generation config passed to the Gemini client."""

    config: MutableMapping[str, Any] = {}
    raw = config_obj.raw.get("generation_config")
    if isinstance(raw, Mapping):
        config.update(raw)
    if config_obj.temperature:
        config.setdefault("temperature", float(config_obj.temperature))
    if config_obj.top_p and config_obj.top_p < 1.0:
        config.setdefault("top_p", float(config_obj.top_p))
    if config_obj.max_tokens:
        config.setdefault("max_output_tokens", int(config_obj.max_tokens))
    return config


def prepare_safety_settings(
    config_obj: ProviderConfig,
) -> Sequence[Mapping[str, Any]] | None:
    """Return sanitized safety settings derived from provider config."""

    raw = config_obj.raw.get("safety_settings")
    if isinstance(raw, Sequence):
        candidates: list[Mapping[str, Any]] = []
        for item in raw:
            if isinstance(item, Mapping):
                candidates.append(dict(item))
        if candidates:
            return candidates
    return None
