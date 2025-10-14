"""Compatibility package marker for src namespace."""

from importlib import import_module
from types import ModuleType

__all__ = ["llm_adapter"]


def __getattr__(name: str) -> ModuleType:
    if name == "llm_adapter":
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
