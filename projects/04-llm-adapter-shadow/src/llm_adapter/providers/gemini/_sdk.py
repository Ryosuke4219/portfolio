"""Compatibility helpers for the google-genai SDK."""

from __future__ import annotations

from types import ModuleType
from typing import Any, cast

try:  # pragma: no cover - import guard for offline test environments
    from google import genai as _genai_module
    from google.genai import types as _genai_types
except ModuleNotFoundError:  # pragma: no cover - fallback when SDK is unavailable
    genai: ModuleType | None = None
    gt: Any | None = None
else:
    genai = cast(ModuleType, _genai_module)
    gt = cast(Any, _genai_types)

if gt is None:  # pragma: no cover - stub for unit tests without the SDK

    class _GenerateContentConfig(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

        def to_dict(self) -> dict[str, Any]:
            return dict(self)

    class _TypesModule:
        GenerateContentConfig = _GenerateContentConfig

    gt = cast(Any, _TypesModule())

__all__ = ["genai", "gt"]
