from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable

_TARGET = Path(__file__).name


def _should_bridge(argv: Iterable[str]) -> bool:
    return any(Path(arg).name == _TARGET for arg in list(argv)[1:])


__all__: list[str] = []

if _should_bridge(sys.argv):
    from .ollama import conftest as _ollama_conftest
    from .ollama import test_retriable_errors, test_streaming, test_success

    def _forward(module: ModuleType) -> None:
        for name in dir(module):
            if name.startswith("test_"):
                globals()[name] = getattr(module, name)
                __all__.append(name)

    for fixture_name in (
        "fake_client_installer",
        "ollama_module",
        "provider_config_factory",
    ):
        globals()[fixture_name] = getattr(_ollama_conftest, fixture_name)

    _forward(test_success)
    _forward(test_streaming)
    _forward(test_retriable_errors)
