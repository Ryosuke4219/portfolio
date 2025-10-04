from importlib import util
from pathlib import Path
from types import ModuleType


def _load_consume_cases() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "tools" / "consume_cases.py"
    spec = util.spec_from_file_location("consume_cases", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive guard
        raise RuntimeError("failed to load consume_cases module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


consume_cases = _load_consume_cases()
_build_metrics = consume_cases._build_metrics
_format_text = consume_cases._format_text


def test_build_metrics_normalizes_errored_status() -> None:
    cases = {
        "suite": "demo-suite",
        "cases": [
            {"id": "case-1"},
        ],
    }
    attempts = [
        {
            "name": "case-1 first attempt",
            "status": "errored",
        }
    ]

    metrics = _build_metrics(cases, attempts)

    assert metrics["status_breakdown"].get("error") == 1
    assert "errored" not in metrics["status_breakdown"]

    text = _format_text(metrics)
    assert "error: 1" in text


def test_build_metrics_normalizes_failed_status() -> None:
    cases = {
        "suite": "demo-suite",
        "cases": [
            {"id": "case-1"},
        ],
    }
    attempts = [
        {
            "name": "case-1 first attempt",
            "status": "failed",
        }
    ]

    metrics = _build_metrics(cases, attempts)

    assert metrics["status_breakdown"].get("fail") == 1
    assert "failed" not in metrics["status_breakdown"]

    text = _format_text(metrics)
    assert "fail: 1" in text
