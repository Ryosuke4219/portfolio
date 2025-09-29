"""トップレベル `adapter` パッケージのシム。"""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET_DIR = _REPO_ROOT / "projects" / "04-llm-adapter" / "adapter"
_SHADOW_SRC_ROOT = _REPO_ROOT / "projects" / "04-llm-adapter-shadow"
if not _TARGET_DIR.exists():  # pragma: no cover - 開発環境の構成不備
    raise ImportError("projects/04-llm-adapter/adapter が見つかりません")
if _SHADOW_SRC_ROOT.exists():
    shadow_path = str(_SHADOW_SRC_ROOT)
    if shadow_path not in sys.path:
        sys.path.insert(0, shadow_path)

_spec = spec_from_file_location(
    __name__,
    _TARGET_DIR / "__init__.py",
    submodule_search_locations=[str(_TARGET_DIR)],
)
if _spec is None or _spec.loader is None:  # pragma: no cover - importlib 異常
    raise ImportError("adapter モジュールのロードに失敗しました")

_module = module_from_spec(_spec)
sys.modules[__name__] = _module
_spec.loader.exec_module(_module)

globals().update({k: v for k, v in _module.__dict__.items() if k != "__dict__"})
