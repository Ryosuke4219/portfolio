from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent.parent
project_path = str(PROJECT_ROOT)
if project_path not in sys.path:
    sys.path.insert(0, project_path)

# Ensure the canonical adapter package is loaded before shadow paths can override it.
importlib.import_module("adapter")

from adapter.core.compare_runner_support import RunMetricsBuilder
from adapter.core.runner_config_builder import RunnerMode

SHADOW_ROOT = PROJECT_ROOT.parent / "04-llm-adapter-shadow"
if SHADOW_ROOT.exists():
    shadow_path = str(SHADOW_ROOT)
    if shadow_path not in sys.path:
        sys.path.append(shadow_path)


if (
    RunMetricsBuilder._resolve_canonical_mode(  # type: ignore[misc]
        RunnerMode.PARALLEL_ANY, RunnerMode.PARALLEL_ANY
    )
    != RunnerMode.PARALLEL_ANY.value
):

    def _resolve_canonical_mode(mode: object, resolved_mode: object) -> str:
        for candidate in (mode, resolved_mode):
            canonical = getattr(candidate, "canonical", None)
            if isinstance(canonical, str) and canonical:
                if canonical.startswith("RunnerMode.") and hasattr(candidate, "value"):
                    value = getattr(candidate, "value")
                    if isinstance(value, str):
                        return value
                return canonical
            if isinstance(candidate, RunnerMode):
                return candidate.value
            value_attr = getattr(candidate, "value", None)
            if isinstance(value_attr, str):
                return value_attr

        source = getattr(resolved_mode, "value", resolved_mode)
        normalized = str(source).strip().lower().replace("-", "_")
        if normalized.startswith("runnermode.") and isinstance(resolved_mode, RunnerMode):
            return resolved_mode.value
        return normalized

    RunMetricsBuilder._resolve_canonical_mode = staticmethod(_resolve_canonical_mode)


def pytest_configure(config):  # pragma: no cover - pytest hook
    if config.pluginmanager.hasplugin("asyncio"):
        config.option.asyncio_default_fixture_loop_scope = "function"


def pytest_ignore_collect(collection_path: Path, config):  # pragma: no cover - pytest hook
    if os.environ.get("PYTEST_RUNNER_RETRY_DIRECT") != "1":
        return False
    try:
        candidate = collection_path.resolve()
    except OSError:
        return False
    shadow_tests = SHADOW_ROOT / "tests"
    root_shadow_tests = REPO_ROOT / "tests" / "shadow"
    if shadow_tests in candidate.parents or candidate == shadow_tests:
        return True
    if root_shadow_tests in candidate.parents or candidate == root_shadow_tests:
        return True
    return False
