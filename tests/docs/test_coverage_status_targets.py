from __future__ import annotations

import json
from pathlib import Path

import pytest

STATUS_PATH = Path("docs/reports/coverage/status.json")


def test_coverage_status_targets_are_main_project_only() -> None:
    payload = json.loads(STATUS_PATH.read_text())
    files = payload.get("files")
    assert isinstance(files, dict), "status.json の files セクションが欠落しています"

    offending_paths: list[str] = []
    for file_data in files.values():
        if not isinstance(file_data, dict):
            continue
        index = file_data.get("index")
        if not isinstance(index, dict):
            continue
        file_path = index.get("file")
        if not isinstance(file_path, str):
            continue
        if "projects/04-llm-adapter-shadow/" in file_path:
            offending_paths.append(file_path)

    if offending_paths:
        formatted = ", ".join(sorted(set(offending_paths)))
        pytest.fail(
            f"RED: docs coverage status includes shadow project paths: {formatted}"
        )
