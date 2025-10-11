from __future__ import annotations

import importlib
import sys

from .compare_runner_parallel import _sys_path as _sys_path_module


def test_ensure_import_paths_never_adds_shadow_directory() -> None:
    module = importlib.reload(_sys_path_module)
    shadow_path = str(module.SHADOW_ROOT)
    project_path = str(module.PROJECT_ROOT)

    sys.path[:] = [p for p in sys.path if p != shadow_path]

    module.ensure_import_paths()

    assert project_path in sys.path
    assert shadow_path not in sys.path
