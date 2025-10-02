from __future__ import annotations

from collections.abc import Callable, Sequence
import importlib.util
import json
from pathlib import Path
import sys
from typing import cast, Protocol


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


MainFunc = Callable[[Sequence[str] | None], None]


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
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    main = module.main
    assert callable(main)
    return main


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
