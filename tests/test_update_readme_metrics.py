from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def load_update_readme_metrics_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "tools" / "update_readme_metrics.py"
    spec = spec_from_file_location("update_readme_metrics", module_path)
    if spec is None or spec.loader is None:
        msg = "Failed to load update_readme_metrics module"
        raise RuntimeError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_format_top_flaky_includes_numeric_score() -> None:
    module = load_update_readme_metrics_module()

    rows = [
        {"canonical_id": "workflow-alpha", "score": 0.12345},
        {"canonical_id": "workflow-beta", "score": None},
    ]

    result = module.format_top_flaky(rows)

    assert result == "1. workflow-alpha (score 0.12)<br/>2. workflow-beta"
