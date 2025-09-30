"""CI report processing and rendering helpers."""

from .processing import compute_last_updated, normalize_flaky_rows, summarize_failure_kinds
from .rendering import build_json_payload, render_markdown

__all__ = [
    "build_json_payload",
    "compute_last_updated",
    "normalize_flaky_rows",
    "render_markdown",
    "summarize_failure_kinds",
]
