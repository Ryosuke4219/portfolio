from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable


class _SrcImportRecorder:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(
        self,
        fullname: str,
        path: Iterable[str] | None = None,
        target: object | None = None,
    ) -> None:
        if fullname == "src" or fullname.startswith("src.llm_adapter"):
            self.attempts.append(fullname)
        return None


def _assert_no_shadow_import(module_name: str) -> None:
    recorder = _SrcImportRecorder()
    sys.modules.pop(module_name, None)
    sys.meta_path.insert(0, recorder)
    try:
        importlib.invalidate_caches()
        importlib.import_module(module_name)
    finally:
        sys.meta_path.remove(recorder)
    assert not recorder.attempts
    assert not any(name.startswith("src.llm_adapter") for name in sys.modules)


def test_shadow_helpers_does_not_shadow_import() -> None:
    _assert_no_shadow_import("adapter.core._shadow_helpers")


def test_parallel_shim_does_not_shadow_import() -> None:
    _assert_no_shadow_import("adapter.core._parallel_shim")
