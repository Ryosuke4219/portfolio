"""pytest グローバル設定: ルートパスと tools パッケージの解決を安定化。"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parent
if _REPO_ROOT.name == "tests":
    _REPO_ROOT = _REPO_ROOT.parent

_ROOT_STR = str(_REPO_ROOT)
if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)

_TOOLS_ROOT = (_REPO_ROOT / "tools").resolve()
_loaded = sys.modules.get("tools")
if _loaded is not None:
    module_path = getattr(_loaded, "__file__", None)
    if module_path is None or not Path(module_path).resolve().is_relative_to(_TOOLS_ROOT):
        sys.modules.pop("tools", None)

if "tools" not in sys.modules:
    importlib.import_module("tools")
