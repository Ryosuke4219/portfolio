"""Utility scripts and helpers for repository tooling."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType

_current_dir = Path(__file__).resolve().parent
_legacy_tools = _current_dir.parent / "projects" / "04-llm-adapter" / "tools"

__path__ = [str(_current_dir)]
if _legacy_tools.exists():
    __path__.append(str(_legacy_tools))

__all__: list[str] = []


def _ensure_namespace(package: str, location: Path) -> ModuleType:
    module = sys.modules.get(package)
    if module is not None:
        return module
    namespace = ModuleType(package)
    namespace.__file__ = str(location / "__init__.py") if (location / "__init__.py").exists() else str(location)
    namespace.__path__ = [str(location)]
    sys.modules[package] = namespace
    return namespace


def _load_package(alias: str, origin: Path) -> None:
    if alias in sys.modules:
        return
    spec = spec_from_file_location(alias, origin, submodule_search_locations=[str(origin.parent)])
    if spec is None or spec.loader is None:
        return
    module = module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPORT_ROOT = _REPO_ROOT / "projects" / "04-llm-adapter" / "tools" / "report"
_METRICS_ROOT = _REPORT_ROOT / "metrics"

if _METRICS_ROOT.exists():
    _ensure_namespace("tools.report", _REPORT_ROOT)
    _load_package("tools.report.metrics", _METRICS_ROOT / "__init__.py")
    metrics_to_html = _REPORT_ROOT / "metrics_to_html.py"
    if metrics_to_html.exists():
        _load_package("tools.report.metrics_to_html", metrics_to_html)

