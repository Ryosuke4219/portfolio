"""Shadow adapter package exposing config loading helpers for tests."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

_PACKAGE_ROOT = Path(__file__).resolve().parent
_CORE_REPO_ADAPTER = _PACKAGE_ROOT.parents[1] / "04-llm-adapter" / "adapter"
if _CORE_REPO_ADAPTER.exists():
    _spec = spec_from_file_location(
        __name__,
        _CORE_REPO_ADAPTER / "__init__.py",
        submodule_search_locations=[str(_CORE_REPO_ADAPTER)],
    )
    if _spec is None or _spec.loader is None:  # pragma: no cover - importlib failure
        raise ImportError("adapter パッケージのロードに失敗しました")
    _module = module_from_spec(_spec)
    sys.modules[__name__] = _module
    _spec.loader.exec_module(_module)
    globals().update({k: v for k, v in _module.__dict__.items() if k != "__dict__"})
else:
    from .core.config import ConfigError, ProviderConfig, load_provider_config

    __all__ = ["ConfigError", "ProviderConfig", "load_provider_config"]
