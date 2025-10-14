import importlib
import importlib.abc
from importlib.machinery import ModuleSpec
import importlib.util
import sys
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


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, alias_name: str, actual_name: str) -> None:
        self._alias_name = alias_name
        self._actual_name = actual_name

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        actual = importlib.import_module(self._actual_name)
        sys.modules[self._alias_name] = actual


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: object,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if not fullname.startswith("llm_adapter."):
            return None
        actual_name = ".".join(("src", fullname))
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


def _install_aliases() -> None:
    module = sys.modules[__name__]
    sys.modules["llm_adapter"] = module
    package_name = __name__.split(".", 1)[-1]
    src_package = ".".join(("src", package_name))
    sys.modules[src_package] = module

    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _alias_finder)

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
