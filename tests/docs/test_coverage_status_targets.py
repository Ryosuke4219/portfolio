from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

from _pytest.outcomes import Failed
import pytest

STATUS_PATH = Path("docs/reports/coverage/status.json")
SHADOW_PATH_FRAGMENT = "projects/04-llm-adapter-shadow/"


def _iter_strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        yield node
        return
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
        return
    if isinstance(node, list):
        for value in node:
            yield from _iter_strings(value)


def _assert_shadow_paths_absent(files_section: Any) -> None:
    offending_paths = sorted(
        {
            value
            for value in _iter_strings(files_section)
            if SHADOW_PATH_FRAGMENT in value
        }
    )
    if offending_paths:
        formatted = ", ".join(offending_paths)
        pytest.fail(
            f"RED: docs coverage status includes shadow project paths: {formatted}"
        )


def test_shadow_paths_trigger_red_failure() -> None:
    sample_payload = {
        "dummy": {
            "index": {
                "file": "projects/04-llm-adapter-shadow/src/example.py",
                "html_filename": "z_dummy_example.html",
            }
        }
    }

    with pytest.raises(Failed) as excinfo:
        _assert_shadow_paths_absent(sample_payload)

    message = str(excinfo.value)
    assert message.startswith("RED: docs coverage status includes shadow project paths: ")
    assert "projects/04-llm-adapter-shadow/src/example.py" in message


def test_coverage_status_targets_are_main_project_only() -> None:
    payload = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    files = payload.get("files")
    assert isinstance(files, dict), "status.json の files セクションが欠落しています"

    _assert_shadow_paths_absent(files)
