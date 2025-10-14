import importlib
import importlib.abc
import importlib.util
import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec, PathFinder
from types import ModuleType

from .errors import (
    AuthError as AuthError,
    FatalError as FatalError,
    RateLimitError as RateLimitError,
    RetriableError as RetriableError,
    TimeoutError as TimeoutError,
)
from .provider_spi import (
    ProviderRequest as ProviderRequest,
    ProviderResponse as ProviderResponse,
    ProviderSPI as ProviderSPI,
)
from .runner import Runner as Runner
from .shadow import run_with_shadow as run_with_shadow

__version__ = "0.1.0"


def _register_module_alias(actual_name: str, alias_name: str) -> ModuleType:
    actual_module = sys.modules[actual_name]
    existing = sys.modules.get(alias_name)
    if existing is not actual_module:
        sys.modules[alias_name] = actual_module
    return actual_module


_SRC_PREFIX = "src."
_PACKAGE_NAME = __name__.split(".", 1)[-1]
_SHADOW_PACKAGE = f"{_SRC_PREFIX}{_PACKAGE_NAME}"
_SHADOW_PREFIX = f"{_SHADOW_PACKAGE}."


def _strip_src_prefix(name: str) -> str:
    if name.startswith(_SRC_PREFIX):
        return name[len(_SRC_PREFIX):]
    return name


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, alias_name: str, actual_name: str) -> None:
        self._alias_name = alias_name
        self._actual_name = actual_name

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        placeholder = sys.modules.pop(self._alias_name, None)
        try:
            importlib.import_module(self._actual_name)
        except Exception:
            if placeholder is not None:
                sys.modules[self._alias_name] = placeholder
            raise
        _register_module_alias(self._actual_name, self._alias_name)


class _ActualAliasLoader(importlib.abc.Loader):
    def __init__(self, delegate: importlib.abc.Loader, actual_name: str, alias_name: str) -> None:
        self._delegate = delegate
        self._actual_name = actual_name
        self._alias_name = alias_name

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        if hasattr(self._delegate, "create_module"):
            return self._delegate.create_module(spec)
        return None

    def exec_module(self, module: ModuleType) -> None:
        if hasattr(self._delegate, "exec_module"):
            self._delegate.exec_module(module)
        else:
            raise ImportError(f"Loader for {self._actual_name!r} does not implement exec_module")
        _register_module_alias(self._actual_name, self._alias_name)


class _ExistingModuleLoader(importlib.abc.Loader):
    def __init__(
        self,
        module: ModuleType,
        actual_name: str,
        alias_name: str,
    ) -> None:
        self._module = module
        self._actual_name = actual_name
        self._alias_name = alias_name
        self._original_spec = getattr(module, "__spec__", None)
        self._original_package = module.__package__

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        return self._module

    def exec_module(self, module: ModuleType) -> None:
        sys.modules[self._actual_name] = self._module
        _register_module_alias(self._actual_name, self._alias_name)
        module.__spec__ = self._original_spec
        module.__package__ = self._original_package


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if not fullname.startswith("llm_adapter."):
            return None
        actual_name = f"{_SRC_PREFIX}{fullname}"
        actual_spec = importlib.util.find_spec(actual_name)
        if actual_spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            _AliasLoader(fullname, actual_name),
            origin=actual_spec.origin,
            is_package=actual_spec.submodule_search_locations is not None,
        )

_alias_finder = _AliasFinder()


class _ActualAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if not fullname.startswith(_SHADOW_PREFIX):
            return None
        alias_name = _strip_src_prefix(fullname)
        alias_module = sys.modules.get(alias_name)
        if alias_module is not None:
            spec = ModuleSpec(
                name=fullname,
                loader=_ExistingModuleLoader(alias_module, fullname, alias_name),
                origin="existing module",
                is_package=hasattr(alias_module, "__path__"),
            )
            alias_spec = getattr(alias_module, "__spec__", None)
            if alias_spec and alias_spec.submodule_search_locations is not None:
                spec.submodule_search_locations = list(alias_spec.submodule_search_locations)
            elif hasattr(alias_module, "__path__"):
                spec.submodule_search_locations = list(alias_module.__path__)
            return spec
        actual_spec = PathFinder.find_spec(fullname, path, target)
        if actual_spec is None or actual_spec.loader is None:
            return actual_spec
        actual_spec.loader = _ActualAliasLoader(actual_spec.loader, fullname, alias_name)
        return actual_spec


_actual_alias_finder = _ActualAliasFinder()


def _install_aliases() -> None:
    module = sys.modules[__name__]
    sys.modules["llm_adapter"] = module
    package_name = __name__.split(".", 1)[-1]
    src_package = ".".join(("src", package_name))
    sys.modules[src_package] = module

    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _alias_finder)
    if not any(isinstance(finder, _ActualAliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _actual_alias_finder)

    shadow_prefix = f"{src_package}."
    public_prefix = f"{package_name}."
    for name in list(sys.modules):
        if name == src_package or name.startswith(shadow_prefix):
            _register_module_alias(name, _strip_src_prefix(name))
        if name == package_name or name.startswith(public_prefix):
            _register_module_alias(name, ".".join(("src", name)))

__all__ = [
    "__version__",
    "AuthError",
    "FatalError",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderSPI",
    "RateLimitError",
    "RetriableError",
    "Runner",
    "TimeoutError",
    "run_with_shadow",
]


_install_aliases()
