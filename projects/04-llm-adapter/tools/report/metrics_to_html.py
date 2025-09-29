"""Backward-compatible shim for the relocated metrics report CLI."""

from __future__ import annotations

from .metrics.cli import main

if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
