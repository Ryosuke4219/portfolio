from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_openrouter_stats_cli_generates_summary(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    metrics = [
        {"provider": "openrouter", "status": "error", "error_type": "RateLimitError"},
        {"provider": "openrouter", "status": "error", "failure_kind": "retryable"},
        {"provider": "openrouter", "status": "ok"},
        {"provider": "openrouter", "status": "error", "failure_kind": "rate_limit"},
        {"provider": "anthropic", "status": "error", "error_type": "RateLimitError"},
    ]
    metrics_path.write_text("\n".join(json.dumps(row) for row in metrics), encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.report.metrics.openrouter_stats",
            "--metrics",
            str(metrics_path),
            "--out",
            str(out_dir),
        ],
        check=True,
    )

    summary_path = out_dir / "openrouter_http_failures.json"
    assert summary_path.exists()

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["total"] == 3
    assert data["rows"] == [
        {
            "category": "RateLimitError",
            "label": "RateLimitError (429)",
            "count": 2,
            "rate": 66.67,
        },
        {
            "category": "RetriableError",
            "label": "RetriableError (5xx)",
            "count": 1,
            "rate": 33.33,
        },
    ]

    summary_jsonl = out_dir / "openrouter_http_failures.jsonl"
    assert summary_jsonl.exists()
    lines = summary_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert rows[0]["category"] == "RateLimitError"
    assert rows[1]["category"] == "RetriableError"
