from __future__ import annotations

from typing import Any

from .args import parse_args
from .config import build_runner_config
from .runner import main, prepare_execution

__all__ = ["parse_args", "build_runner_config", "prepare_execution", "main"]


def __getattr__(name: str) -> Any:
    if name == "_format_output":
        from .io import _format_output as format_output

        return format_output
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
