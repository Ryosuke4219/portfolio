from __future__ import annotations

import sys
from pathlib import Path


def test_shadow_adapter_directory_not_on_sys_path_by_default() -> None:
    tests_dir = Path(__file__).resolve().parent
    project_root = tests_dir.parent
    shadow_root = project_root.parent / "04-llm-adapter-shadow"

    assert shadow_root.exists(), "shadow project directory should exist for guard test"

    normalized_shadow = shadow_root.resolve()
    normalized_sys_paths = {
        Path(path).resolve()
        for path in sys.path
        if path and Path(path).exists()
    }

    assert (
        normalized_shadow not in normalized_sys_paths
    ), "shadow adapter path must not be present on sys.path at session start"
