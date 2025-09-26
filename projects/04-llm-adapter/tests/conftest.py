import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):  # pragma: no cover - pytest hook
    if config.pluginmanager.hasplugin("asyncio"):
        setattr(config.option, "asyncio_default_fixture_loop_scope", "function")
