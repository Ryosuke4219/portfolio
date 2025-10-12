"""consume_cases ツールのテスト."""
from __future__ import annotations

from importlib import util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_consume_cases() -> ModuleType:
    module_path = PROJECT_ROOT / "tools" / "consume_cases.py"
    spec = util.spec_from_file_location("consume_cases", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive guard
        raise RuntimeError("failed to load consume_cases module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


consume_cases = _load_consume_cases()


def test_build_metrics_matches_expected_output(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "suite": "demo-suite",
                "cases": [
                    {"id": "case-1"},
                    {"id": "case-2"},
                ],
            }
        ),
        encoding="utf-8",
    )
    attempts_path = tmp_path / "attempts.jsonl"
    attempts_path.write_text(
        "\n".join(
            [
                json.dumps({"name": "case-1 first", "status": "pass"}),
                json.dumps({"name": "case-2 retry", "status": "errored"}),
                json.dumps({"name": "case-2 retry", "status": "failure"}),
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "consume_cases.py"),
            "--cases",
            str(cases_path),
            "--attempts",
            str(attempts_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["suite"] == "demo-suite"
    assert payload["case_count"] == 2
    assert payload["attempt_count"] == 3
    assert payload["status_breakdown"]["pass"] == 1
    assert payload["status_breakdown"]["fail"] == 1
    assert payload["status_breakdown"]["error"] == 1
    assert payload["failed_case_ids"] == ["case-2"]


def test_build_metrics_normalizes_failed_status() -> None:
    metrics = consume_cases._build_metrics(  # type: ignore[attr-defined]
        {
            "suite": "demo-suite",
            "cases": [{"id": "case-1"}],
        },
        [
            {"name": "case-1 first attempt", "status": "failed"},
        ],
    )

    assert metrics["status_breakdown"].get("fail") == 1
    assert "failed" not in metrics["status_breakdown"]
