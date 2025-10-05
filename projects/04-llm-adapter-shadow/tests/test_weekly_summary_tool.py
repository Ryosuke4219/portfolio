from __future__ import annotations

from collections.abc import Callable, Sequence
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
from typing import cast, Protocol, runtime_checkable


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


MainFunc = Callable[[Sequence[str] | None], None]


@runtime_checkable
class _MainModule(Protocol):
    main: MainFunc


def _load_main() -> MainFunc:
    module_path = (
        Path(__file__).resolve().parent.parent / "tools" / "weekly_summary.py"
    )
    spec = importlib.util.spec_from_file_location("weekly_summary", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader = cast(importlib.abc.Loader, spec.loader)
    loader.exec_module(module)
    assert isinstance(module, _MainModule)
    main_module = cast(_MainModule, module)
    return main_module.main


def test_weekly_summary_generates_expected_markdown(tmp_path: Path) -> None:
    input_path = tmp_path / "runs-metrics.jsonl"
    output_path = tmp_path / "summary.md"

    _write_jsonl(
        input_path,
        [
            {
                "event": "run_metric",
                "outcome": "success",
                "latency_ms": 120,
            },
            {
                "event": "run_metric",
                "outcome": "error",
                "latency_ms": 300,
            },
            {
                "event": "run_metric",
                "status": "success",
                "latency_ms": 180,
            },
            {
                "event": "shadow_diff",
                "diff_kind": "text_mismatch",
            },
            {
                "event": "shadow_diff",
                "diff_kind": "latency_gap",
            },
            {
                "event": "shadow_diff",
            },
        ],
    )

    main = _load_main()
    main(["--input", str(input_path), "--output", str(output_path)])

    expected = "\n".join(
        [
            "# Weekly Shadow Summary",
            "",
            "## Overview",
            "- Total Runs: 3",
            "- Successes: 2",
            "- Failures: 1",
            "- Failure Rate: 33.33%",
            "",
            "## Latency (ms)",
            "- Average: 200.00",
            "- Median: 180.00",
            "- P95: 288.00",
            "",
            "## Outcomes",
            "| Outcome | Count |",
            "|---------|-------|",
            "| success | 2 |",
            "| error | 1 |",
            "",
            "## Shadow Diff Kinds",
            "| diff_kind | Count |",
            "|-----------|-------|",
            "| latency_gap | 1 |",
            "| text_mismatch | 1 |",
            "",
        ]
    )

    assert output_path.read_text(encoding="utf-8") == expected


def test_weekly_summary_counts_ok_status_as_success(tmp_path: Path) -> None:
    input_path = tmp_path / "runs-metrics.jsonl"
    output_path = tmp_path / "summary.md"

    _write_jsonl(
        input_path,
        [
            {
                "event": "run_metric",
                "outcome": "success",
                "latency_ms": 120,
            },
            {
                "event": "run_metric",
                "status": "success",
                "latency_ms": 180,
            },
            {
                "event": "run_metric",
                "status": "ok",
                "latency_ms": 210,
            },
            {
                "event": "run_metric",
                "outcome": "error",
                "latency_ms": 300,
            },
        ],
    )

    main = _load_main()
    main(["--input", str(input_path), "--output", str(output_path)])

    output = output_path.read_text(encoding="utf-8")
    assert "- Total Runs: 4" in output
    assert "- Successes: 3" in output
    assert "- Failures: 1" in output
    assert "| success | 3 |" in output
    assert "| ok |" not in output


def test_weekly_summary_normalizes_errored_status(tmp_path: Path) -> None:
    input_path = tmp_path / "runs-metrics.jsonl"
    output_path = tmp_path / "summary.md"

    _write_jsonl(
        input_path,
        [
            {
                "event": "run_metric",
                "outcome": "success",
                "latency_ms": 120,
            },
            {
                "event": "run_metric",
                "status": "success",
                "latency_ms": 180,
            },
            {
                "event": "run_metric",
                "status": "errored",
                "latency_ms": 250,
            },
            {
                "event": "run_metric",
                "outcome": "error",
                "latency_ms": 300,
            },
        ],
    )

    main = _load_main()
    main(["--input", str(input_path), "--output", str(output_path)])

    output = output_path.read_text(encoding="utf-8")
    assert "| error | 2 |" in output
    assert "errored" not in output
