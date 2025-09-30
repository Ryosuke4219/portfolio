"""Utility scripts and helpers for repository tooling."""
from __future__ import annotations

from pathlib import Path

_current_dir = Path(__file__).resolve().parent
_legacy_tools = _current_dir.parent / "projects" / "04-llm-adapter" / "tools"

__path__ = [str(_current_dir)]
if _legacy_tools.exists():
    __path__.append(str(_legacy_tools))

__all__ = []
